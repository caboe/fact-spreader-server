"""Document submission, review and indexing (PROTOCOL §8)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.contracts.api import (
    ApprovalRequest,
    DocumentInfo,
    DocumentSubmitRequest,
    DocumentSubmitResponse,
    FigureUpdateRequest,
    Job,
    RejectRequest,
    ReviewQueueResponse,
    WithdrawRequest,
)
from app.core.errors import AppError
from app.core.ids import new_id, normalize_text, utcnow
from app.db.models import AuditLog, Document, DocumentVersion, Instance
from app.db.models import Job as JobRow
from app.db.session import get_session
from app.llm.client import LLMClient, LLMError
from app.services.auth import Principal, require_permission
from app.services.documents import (
    create_document,
    document_to_api,
    latest_version,
    queue_review_counts,
    update_corpus_version,
)
from app.services.image_input import extract_image_text, prepare_image
from app.services.input_reader import (
    UrlFetchError,
    UrlSafetyError,
    fetch_readable,
    read_file_bytes,
)

router = APIRouter(prefix="/v1", tags=["documents"])
Submit = Annotated[Principal, Depends(require_permission("documents:submit"))]
Review = Annotated[Principal, Depends(require_permission("documents:review"))]


def _can_see(document: Document, principal: Principal) -> bool:
    return (
        principal.has("documents:review")
        or principal.has("quality:read")
        or document.submitted_by == principal.user_id
    )


async def _load(session: AsyncSession, document_id: str) -> Document:
    document = await session.get(Document, document_id)
    if document is None or document.deleted:
        raise AppError(404, "not_found", "The document does not exist.")
    return document


async def _api(session: AsyncSession, document: Document, principal: Principal) -> DocumentInfo:
    version = await latest_version(session, document)
    return document_to_api(document, version=version, show_identity=_can_see(document, principal))


@router.post("/documents", status_code=202, response_model=DocumentSubmitResponse)
async def submit_document(
    request: Request,
    principal: Submit,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentSubmitResponse:
    content_type = request.headers.get("content-type", "")
    is_multipart = content_type.startswith("multipart/form-data")
    upload_name: str | None = None
    figures: list[dict[str, Any]] = []
    file_text: str | None = None
    try:
        if is_multipart:
            form = await request.form()
            payload_part = form.get("payload")
            if not isinstance(payload_part, str):
                raise AppError(422, "invalid_input", "A multipart document needs a payload.")
            body = DocumentSubmitRequest.model_validate_json(payload_part)
            file_part = None
            for key, value in form.multi_items():
                if key == "file" and isinstance(value, UploadFile):
                    file_part = value
                    break
            if file_part is None:
                raise AppError(422, "invalid_input", "A multipart document needs one file.")
            filename = getattr(file_part, "filename", None) or "upload"
            media = getattr(file_part, "content_type", None) or "application/octet-stream"
            try:
                data = await file_part.read()
            finally:
                await file_part.close()
            settings = request.app.state.settings
            if len(data) > settings.upload_max_bytes:
                raise AppError(413, "payload_too_large", "The uploaded file is too large.")
            if media.startswith("image/") or filename.rsplit(".", 1)[-1].lower() in {
                "png",
                "jpg",
                "jpeg",
                "webp",
                "gif",
            }:
                prepared = prepare_image(data, media, settings)
                try:
                    vision = await extract_image_text(
                        LLMClient(settings, consumer="vision"),
                        prepared,
                        user_id=principal.user_id,
                    )
                except LLMError as exc:
                    raise AppError(502, exc.code, exc.detail) from exc
                file_text = f"# {filename}\n\n{vision.description}\n\n{vision.text}"
                figures.append(
                    {
                        "id": new_id("fig"),
                        "page": None,
                        "number": None,
                        "caption": filename,
                        "description": vision.description,
                        "description_source": "vision",
                        "description_model_id": "fs-vision",
                        "editor_checked": False,
                        "created_at": utcnow().isoformat(),
                    }
                )
            else:
                file_text, title = read_file_bytes(
                    filename=filename, content_type=media, data=data, settings=settings
                )
                if body.metadata.title is None and title:
                    body.metadata.title = title
            upload_name = filename
            upload_size = len(data)
        else:
            body = DocumentSubmitRequest.model_validate(await request.json())
            upload_size = len((body.input.text or "").encode())
        if file_text is not None:
            body.input.text = file_text
    except ValidationError as exc:
        raise AppError(
            422, "validation_error", str(exc.errors()[0].get("msg", "invalid body"))
        ) from exc

    settings = request.app.state.settings
    metadata = body.metadata
    source_url: str | None = None
    page_title: str | None = None
    if body.input.type == "url":
        if not body.input.url:
            raise AppError(422, "invalid_input", "A URL document requires a url.")
        try:
            page = await fetch_readable(body.input.url, settings)
        except UrlSafetyError as exc:
            raise AppError(422, "unsafe_url", str(exc)) from exc
        except UrlFetchError as exc:
            raise AppError(502, "url_fetch_failed", str(exc)) from exc
        content = page.text
        source_url = page.url
        page_title = page.title
        size = page.size_bytes
        content_type = page.content_type
    else:
        content = normalize_text(body.input.text or "")
        size = upload_size
        content_type = "text/markdown" if is_multipart else "text/plain"
    if not content.strip():
        raise AppError(422, "empty_input", "The document has no readable text.")
    decision = request.app.state.language.resolve(content[:4000], metadata.language)
    if metadata.title is None:
        metadata.title = page_title or upload_name or (source_url or "Submitted document")
    instance = (await session.execute(select(Instance).limit(1))).scalar_one()
    try:
        document, version, _warnings, duplicate_of, estimate = await create_document(
            session,
            settings=settings,
            publishers=request.app.state.publishers,
            instance=instance,
            user_id=principal.user_id,
            content=content,
            content_type=content_type,
            size_bytes=size or len(content.encode()),
            metadata=metadata,
            detected_language=decision.detected,
            unsupported_language=decision.unsupported,
            source_url=source_url,
            figures=figures,
            force=body.force,
        )
    except ValueError as exc:
        raise AppError(422, "invalid_input", str(exc)) from exc
    now = utcnow()
    job = JobRow(
        id=new_id("job"),
        kind="document_parse",
        state="done",
        payload={"document_id": document.id, "version": version.version},
        progress=1.0,
        user_id=principal.user_id,
        created_at=now,
        started_at=now,
        finished_at=now,
    )
    session.add(job)
    await session.commit()
    info = await _api(session, document, principal)
    api_job = Job(
        id=job.id,
        kind=job.kind,
        state=job.state,
        progress=1.0,
        created_at=now,
        started_at=now,
        finished_at=now,
        events_url=f"/v1/factcheck/{job.id}/events",
    )
    return DocumentSubmitResponse(
        document=info, job=api_job, estimate=estimate, duplicate_of=duplicate_of
    )


@router.get("/documents/{document_id}", response_model=DocumentInfo)
async def get_document(
    document_id: str,
    principal: Annotated[Principal, Depends(require_permission("documents:submit"))],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentInfo:
    document = await _load(session, document_id)
    if not _can_see(document, principal):
        raise AppError(404, "not_found", "The document does not exist.")
    return await _api(session, document, principal)


@router.get("/documents/{document_id}/content")
async def get_content(
    document_id: str,
    principal: Annotated[Principal, Depends(require_permission("documents:submit"))],
    session: Annotated[AsyncSession, Depends(get_session)],
    version: int | None = None,
) -> Response:
    document = await _load(session, document_id)
    if not _can_see(document, principal):
        raise AppError(404, "not_found", "The document does not exist.")
    if version is None:
        row = await latest_version(session, document)
    else:
        row = (
            await session.execute(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.version == version,
                )
            )
        ).scalar_one_or_none()
    if row is None:
        raise AppError(404, "not_found", "The document version does not exist.")
    return Response(
        content=row.content_md,
        media_type="text/markdown",
        headers={
            "ETag": f'"{row.content_hash}"',
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post("/documents/{document_id}/approve", response_model=DocumentInfo)
async def approve_document(
    document_id: str,
    body: ApprovalRequest,
    request: Request,
    principal: Review,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentInfo:
    document = await _load(session, document_id)
    if document.state not in {"ready", "warning", "parsed"}:
        raise AppError(409, "invalid_state", "The document cannot be approved in this state.")
    if not body.license_confirmed:
        raise AppError(422, "license_not_confirmed", "The license must be confirmed.")
    if request.app.state.settings.four_eyes_enabled and document.submitted_by == principal.user_id:
        raise AppError(403, "four_eyes_required", "A second reviewer must approve this document.")
    now = utcnow()
    document.state = "approved"
    document.approved_by = principal.user_id
    document.approved_at = now
    document.redistribution = body.redistribution
    document.notes = body.note
    document.updated_at = now
    job = JobRow(
        id=new_id("job"),
        kind="document_index",
        state="queued",
        payload={"document_id": document.id, "version": document.version},
        progress=0.0,
        user_id=principal.user_id,
        created_at=now,
    )
    session.add(job)
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=principal.user_id,
            actor_type="user",
            action="document_approved",
            object_type="document",
            object_id=document.id,
            detail={"redistribution": body.redistribution, "note": body.note},
            created_at=now,
        )
    )
    await session.commit()
    return await _api(session, document, principal)


@router.post("/documents/{document_id}/reject", response_model=DocumentInfo)
async def reject_document(
    document_id: str,
    body: RejectRequest,
    principal: Review,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentInfo:
    document = await _load(session, document_id)
    if document.state not in {"ready", "warning", "parsed", "approved"}:
        raise AppError(409, "invalid_state", "The document cannot be rejected in this state.")
    document.state = "rejected"
    document.notes = body.reason
    document.updated_at = utcnow()
    await session.commit()
    return await _api(session, document, principal)


@router.post("/documents/{document_id}/withdraw", response_model=DocumentInfo)
async def withdraw_document(
    document_id: str,
    body: WithdrawRequest,
    request: Request,
    principal: Review,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentInfo:
    document = await _load(session, document_id)
    if document.state not in {"approved", "indexing", "indexed"}:
        raise AppError(409, "invalid_state", "Only an approved document can be withdrawn.")
    try:
        await request.app.state.lightrag.delete_documents([f"{document.id}@v{document.version}"])
    except Exception as exc:
        raise AppError(502, "index_unavailable", "The document could not be removed.") from exc
    document.state = "withdrawn"
    document.notes = body.reason
    document.updated_at = utcnow()
    instance = (await session.execute(select(Instance).limit(1))).scalar_one_or_none()
    if instance is not None:
        await update_corpus_version(session, instance)
    await session.commit()
    return await _api(session, document, principal)


@router.put("/documents/{document_id}/figures/{figure_id}", response_model=DocumentInfo)
async def update_figure(
    document_id: str,
    figure_id: str,
    body: FigureUpdateRequest,
    principal: Review,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentInfo:
    document = await _load(session, document_id)
    figures = [dict(item) for item in (document.figures or []) if isinstance(item, dict)]
    found = False
    for figure in figures:
        if figure.get("id") == figure_id:
            figure["description"] = body.description
            figure["editor_checked"] = True
            figure["editor_checked_by"] = principal.user_id
            found = True
            break
    if not found:
        raise AppError(404, "not_found", "The figure does not exist.")
    document.figures = figures
    document.updated_at = utcnow()
    await session.commit()
    return await _api(session, document, principal)


@router.get("/review/queue", response_model=ReviewQueueResponse)
async def review_queue(
    principal: Review,
    session: Annotated[AsyncSession, Depends(get_session)],
    state: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
) -> ReviewQueueResponse:
    statement = select(Document).where(Document.deleted.is_(False))
    if state:
        statement = statement.where(Document.state == state)
    else:
        statement = statement.where(Document.state.in_(["ready", "warning", "parsed", "duplicate"]))
    rows = (
        (await session.execute(statement.order_by(Document.created_at).limit(limit)))
        .scalars()
        .all()
    )
    data = [await _api(session, row, principal) for row in rows]
    counts = await queue_review_counts(session)
    return ReviewQueueResponse(
        data=data,
        counts=counts,
        summary={"total": sum(counts.values()), "returned": len(data)},
    )
