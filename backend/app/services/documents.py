"""Document submission, review and indexing (PROTOCOL §8).

Content is untrusted data. Submission stores a parsed Markdown version and warnings;
approval is the only path into LightRAG. Indexing runs in the worker with
``file_source = <doc_id>@v<version>`` so stored evidence keeps a resolvable provenance.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    DocumentApproval,
    DocumentEstimate,
    DocumentFigure,
    DocumentInfo,
    DocumentMetadata,
    DocumentWarning,
)
from app.contracts.enums import TurnType
from app.core.config import Settings
from app.core.ids import new_id, sha256_text, utcnow
from app.db.models import Document, DocumentVersion, Instance, Result
from app.db.models import Job as JobRow
from app.llm.client import LLMClient
from app.retrieval.lightrag import LightRAGClient, LightRAGError
from app.services.checks import create_check_job
from app.services.image_input import extract_image_text, prepare_image
from app.services.input_reader import UrlFetchError, read_file_bytes
from app.services.methodology import Methodology
from app.services.methodology_overrides import effective_methodology_for
from app.services.publishers import PublisherRegistry

logger = logging.getLogger(__name__)


def extract_pdf_tables(data: bytes, *, max_pages: int = 20, max_tables: int = 10) -> str:
    """Return PDF tables as Markdown blocks, bounded by page and table count."""
    try:
        from io import BytesIO

        import pdfplumber

        sections: list[str] = []
        with pdfplumber.open(BytesIO(data)) as pdf:
            for page_number, page in enumerate(pdf.pages[:max_pages], start=1):
                for table_index, table in enumerate(page.extract_tables(), start=1):
                    rows = [
                        [" ".join((cell or "").split()).replace("|", "\\|") for cell in row]
                        for row in table
                        if row
                    ]
                    if not rows:
                        continue
                    width = max(len(row) for row in rows)
                    padded = [row + [""] * (width - len(row)) for row in rows]
                    lines = ["| " + " | ".join(padded[0]) + " |"]
                    lines.append("| " + " | ".join(["---"] * width) + " |")
                    for row in padded[1:]:
                        lines.append("| " + " | ".join(row) + " |")
                    sections.append(
                        f"## Table: page {page_number} table {table_index}\n\n" + "\n".join(lines)
                    )
                    if len(sections) >= max_tables:
                        return "\n\n".join(sections)
        return "\n\n".join(sections)
    except Exception:
        logger.warning("pdf_table_extraction_failed")
        return ""


async def parse_pdf_assets(
    data: bytes,
    *,
    settings: Settings,
    user_id: str | None,
    request_id: str | None = None,
) -> tuple[str, list[dict[str, Any]], list[str], int]:
    """Return (table_markdown, figures, figure_sections, page_count) for a PDF.

    Vision calls carry the caller's request id so a batch can aggregate their usage.
    """
    tables = extract_pdf_tables(data)
    figures: list[dict[str, Any]] = []
    sections: list[str] = []
    images = extract_pdf_images(data)
    llm = LLMClient(settings, consumer="vision", request_id=request_id)
    for index, (page_number, image_bytes) in enumerate(images, start=1):
        try:
            prepared = prepare_image(image_bytes, "image/png", settings)
            vision = await extract_image_text(llm, prepared, user_id=user_id)
        except (UrlFetchError, Exception):
            continue
        label = f"Page {page_number} image {index}"
        figures.append(
            {
                "id": new_id("fig"),
                "page": page_number,
                "number": str(index),
                "caption": label,
                "description": vision.description,
                "description_source": "vision",
                "description_model_id": "fs-vision",
                "editor_checked": False,
                "created_at": utcnow().isoformat(),
            }
        )
        sections.append(f"## Figure: {label}\n\n{vision.description}\n\n{vision.text}")
    try:
        from io import BytesIO

        from pypdf import PdfReader

        pages = len(PdfReader(BytesIO(data)).pages)
    except Exception:
        pages = max(1, len(data) // 100_000 + 1)
    return tables, figures, sections, pages


def extract_pdf_images(data: bytes, limit: int = 5) -> list[tuple[int, bytes]]:
    """Return up to ``limit`` embedded PDF images with their 1-based page number."""
    try:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        images: list[tuple[int, bytes]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            for image in page.images:
                payload = getattr(image, "data", None)
                if isinstance(payload, bytes) and payload:
                    images.append((page_number, payload))
                if len(images) >= limit:
                    return images
        return images
    except Exception:
        logger.warning("pdf_image_extraction_failed")
        return []


_INJECTION = re.compile(
    r"(ignore (all )?(previous|prior|above) instructions|system prompt|"
    r"you are now|developer message|jailbreak|do not follow the rules)",
    re.IGNORECASE,
)


def _warnings(
    *,
    content: str,
    language: str,
    supported: list[str],
    license_: str | None,
    quality: str,
    duplicate_of: str | None,
) -> list[DocumentWarning]:
    warnings: list[DocumentWarning] = []
    if duplicate_of:
        warnings.append(
            DocumentWarning(
                code="duplicate_suspected",
                message=f"A near-duplicate of {duplicate_of} exists.",
            )
        )
    if language not in supported:
        warnings.append(
            DocumentWarning(
                code="unsupported_language",
                message=f"The document language {language!r} is not supported.",
            )
        )
    if not license_:
        warnings.append(
            DocumentWarning(
                code="license_missing",
                message="No license is recorded; the editor must confirm the metadata.",
            )
        )
    if quality == "D":
        warnings.append(
            DocumentWarning(
                code="low_source_grade",
                message="The publisher resolves to source grade D.",
            )
        )
    if _INJECTION.search(content):
        warnings.append(
            DocumentWarning(
                code="injection_suspected",
                message="The document contains text that looks like an instruction.",
            )
        )
    return warnings


def document_to_api(
    document: Document,
    *,
    version: DocumentVersion | None,
    show_identity: bool,
    warnings: list[DocumentWarning] | None = None,
) -> DocumentInfo:
    approval = None
    if document.approved_at and document.approved_by:
        approval = DocumentApproval(
            approved_at=document.approved_at,
            approved_by=document.approved_by if show_identity else "usr_redacted",
            note=document.notes,
        )
    figures = [
        DocumentFigure.model_validate(item)
        for item in (document.figures or [])
        if isinstance(item, dict)
    ]
    return DocumentInfo(
        id=document.id,
        version=document.version,
        content_hash=document.content_hash,
        title=document.title,
        publisher=document.publisher,
        authors=list(document.authors or []),
        publication_date=document.publication_date,
        url=document.url,
        doi=document.doi,
        dataset_id=document.dataset_id,
        source_quality=document.source_quality,
        source_quality_basis=dict(document.source_quality_basis or {}),
        domain_tags=list(document.domain_tags or []),
        language=document.language,
        license=document.license,
        redistribution=document.redistribution,
        curator_organization=document.curator_organization,
        origin_instance_id=document.origin_instance_id,
        origin_document_id=document.origin_document_id,
        provenance_chain=(
            [{"instance_id": document.origin_instance_id, "approved_at": document.approved_at}]
            if document.approved_at
            else []
        ),
        content_type=document.content_type,
        size_bytes=version.size_bytes if version else 0,
        state=document.state,
        warnings=warnings
        if warnings is not None
        else [
            DocumentWarning.model_validate(item)
            for item in (document.warnings or [])
            if isinstance(item, dict)
        ],
        duplicate_of=document.duplicate_of,
        submitted_by=document.submitted_by if show_identity else None,
        approval=approval,
        figures=figures,
        approval_preselected=document.state in {"ready", "parsed"} and not document.warnings,
        created_at=document.created_at,
        updated_at=document.updated_at,
        deleted=document.deleted,
    )


async def latest_version(session: AsyncSession, document: Document) -> DocumentVersion | None:
    return (
        await session.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document.id)
            .order_by(DocumentVersion.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _estimate(content: str, figures: list[dict[str, Any]]) -> DocumentEstimate:
    pages = max(1, len(content) // 3000 + 1)
    figure_count = len(figures)
    estimated = round(figure_count * 0.003 + pages * 0.0001, 6)
    return DocumentEstimate(
        pages=pages,
        figures=figure_count,
        vision_calls=figure_count,
        estimated_usd=estimated,
        exceeds_budget=False,
    )


async def create_document(
    session: AsyncSession,
    *,
    settings: Settings,
    publishers: PublisherRegistry,
    instance: Instance,
    user_id: str | None,
    content: str,
    content_type: str,
    size_bytes: int,
    metadata: DocumentMetadata,
    detected_language: str,
    unsupported_language: bool,
    source_url: str | None,
    figures: list[dict[str, Any]] | None = None,
    force: bool = False,
    batch_id: str | None = None,
    source_name: str | None = None,
) -> tuple[Document, DocumentVersion, list[DocumentWarning], str | None, DocumentEstimate]:
    content = content.strip()
    if not content:
        raise ValueError("empty document")
    content_hash = sha256_text(content)
    existing = (
        await session.execute(
            select(Document)
            .where(Document.content_hash == content_hash, Document.deleted.is_(False))
            .order_by(Document.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    duplicate_of = None
    if existing is not None and not force:
        duplicate_of = existing.id
    publisher = (
        metadata.publisher or existing.publisher if existing else metadata.publisher
    ) or "Unknown"
    url = metadata.url or source_url or (existing.url if existing else None)
    doi = metadata.doi or (existing.doi if existing else None)
    quality = publishers.resolve(publisher=publisher, url=url, doi=doi)
    if metadata.source_quality_override:
        quality_grade = metadata.source_quality_override.upper()
        basis = {"source": "document_override", "entry": "submission"}
    else:
        quality_grade = quality.grade
        basis = quality.basis.model_dump(mode="json")
    language = metadata.language or detected_language
    warnings = _warnings(
        content=content,
        language=language,
        supported=settings.supported_languages,
        license_=metadata.license,
        quality=quality_grade,
        duplicate_of=duplicate_of,
    )
    now = utcnow()
    document_id = new_id("doc")
    document = Document(
        id=document_id,
        title=(metadata.title or "Untitled document")[:500],
        publisher=publisher[:300],
        authors=list(metadata.authors or []),
        publication_date=metadata.publication_date,
        url=url,
        doi=doi,
        dataset_id=metadata.dataset_id,
        source_quality=quality_grade,
        source_quality_basis=basis,
        domain_tags=list(metadata.domain_tags or []),
        language=language,
        license=metadata.license,
        redistribution=metadata.redistribution or "metadata_only",
        curator_organization=instance.organization,
        origin_instance_id=instance.id,
        origin_document_id=document_id,
        content_hash=content_hash,
        state="duplicate" if duplicate_of else ("warning" if warnings else "ready"),
        version=1,
        content_type=content_type,
        warnings=[item.model_dump(mode="json") for item in warnings],
        figures=figures or [],
        duplicate_of=duplicate_of,
        batch_id=batch_id,
        submitted_by=user_id,
        deleted=False,
        created_at=now,
        updated_at=now,
    )
    version = DocumentVersion(
        id=new_id("ver"),
        document_id=document_id,
        version=1,
        content_hash=content_hash,
        content_md=content,
        file_path=source_name,
        size_bytes=size_bytes,
        created_at=now,
    )
    session.add_all([document, version])
    await session.flush()
    return document, version, warnings, duplicate_of, _estimate(content, figures or [])


async def update_corpus_version(session: AsyncSession, instance: Instance) -> None:
    docs = (
        await session.execute(
            select(Document.id, Document.version, Document.content_hash).where(
                Document.deleted.is_(False), Document.state == "indexed"
            )
        )
    ).all()
    payload = json.dumps(sorted([list(row) for row in docs]), sort_keys=True)
    instance.corpus_version = "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
    instance.updated_at = utcnow()


async def run_document_index_job(
    session: AsyncSession,
    *,
    settings: Settings,
    lightrag: LightRAGClient,
    job: JobRow,
) -> None:
    payload = job.payload or {}
    document = await session.get(Document, str(payload.get("document_id") or ""))
    if document is None:
        raise ValueError("document_missing")
    version = await latest_version(session, document)
    if version is None:
        raise ValueError("document_version_missing")
    document.state = "indexing"
    document.updated_at = utcnow()
    await session.commit()
    file_source = f"{document.id}@v{document.version}"
    await lightrag.insert_text(
        content=version.content_md, file_source=file_source, title=document.title
    )
    if not await lightrag.wait_until_idle(timeout_seconds=900):
        raise LightRAGError("LightRAG did not finish indexing the document")
    document.state = "indexed"
    document.updated_at = utcnow()
    instance = (await session.execute(select(Instance).limit(1))).scalar_one_or_none()
    if instance is not None:
        await update_corpus_version(session, instance)
    publishers = PublisherRegistry.from_path(settings.publisher_list_path)
    methodology = await effective_methodology_for(
        session, settings.checklist_dir, settings.pattern_list_path
    )
    summary = await enqueue_rechecks_for_document(
        session,
        settings=settings,
        publishers=publishers,
        methodology=methodology,
        document=document,
        reason="corpus_changed",
    )
    _record_recheck_summary(document, summary)
    logger.info(
        "document_rechecks_enqueued",
        extra={
            "event": "document",
            "enqueued": summary["enqueued"],
            "skipped": summary["skipped_budget"],
        },
    )
    await session.commit()
    logger.info("document_indexed", extra={"event": "document", "document_id": document.id})


async def queue_review_counts(session: AsyncSession) -> dict[str, int]:
    rows = (
        await session.execute(
            select(Document.state, func.count(Document.id))
            .where(Document.deleted.is_(False))
            .group_by(Document.state)
        )
    ).all()
    counts = {str(state): int(count) for state, count in rows}
    return {
        "ready": counts.get("ready", 0) + counts.get("parsed", 0),
        "warnings": counts.get("warning", 0),
        "duplicates": counts.get("duplicate", 0),
        "failed": counts.get("failed", 0),
        "approved": counts.get("approved", 0),
        "indexing": counts.get("indexing", 0),
        "indexed": counts.get("indexed", 0),
        "rejected": counts.get("rejected", 0),
        "withdrawn": counts.get("withdrawn", 0),
    }


def _record_recheck_summary(document: Document, summary: dict[str, int]) -> None:
    if not summary.get("skipped_budget"):
        return
    warnings = [dict(item) for item in (document.warnings or []) if isinstance(item, dict)]
    warnings = [item for item in warnings if item.get("code") != "budget_low"]
    warnings.append(
        {
            "code": "budget_low",
            "message": (
                f"{summary['skipped_budget']} affected claim(s) were not re-checked: the "
                "daily re-check budget is exhausted."
            ),
        }
    )
    document.warnings = warnings


async def enqueue_rechecks_for_document(
    session: AsyncSession,
    *,
    settings: Settings,
    publishers: PublisherRegistry,
    methodology: Methodology,
    document: Document,
    reason: str,
) -> dict[str, int]:
    """Queue re-checks for claims affected by an approval or withdrawal.

    Approval matches statements by domain tag; withdrawal matches results whose evidence
    references the document. The daily re-check budget is a hard cap; the return value
    reports how many were skipped for the editor instead of dropping them silently.
    """
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = int(
        (
            await session.execute(
                select(func.count(JobRow.id)).where(
                    JobRow.created_at >= today,
                    JobRow.payload["recheck"].astext == "true",
                )
            )
        ).scalar_one()
    )
    remaining = max(0, settings.recheck_daily_budget - used)
    candidates = (
        (
            await session.execute(
                select(Result)
                .where(
                    Result.deleted.is_(False),
                    Result.status == "complete",
                    Result.preliminary.is_(False),
                )
                .order_by(Result.created_at.desc())
                .limit(200)
            )
        )
        .scalars()
        .all()
    )
    claim_texts: set[str] = set()
    enqueued = 0
    skipped = 0
    for row in candidates:
        if reason == "withdrawal":
            related = any(
                str((item.get("provenance") or {}).get("document_id")) == document.id
                for item in (row.evidence or [])
                if isinstance(item, dict)
            )
        else:
            related = any(
                set(statement.get("domain_tags") or []) & set(document.domain_tags or [])
                for statement in (row.statements or [])
                if isinstance(statement, dict)
            )
        if not related:
            continue
        text = str((row.input or {}).get("text") or "").strip()
        normalized = text.casefold()
        if not text or normalized in claim_texts:
            continue
        claim_texts.add(normalized)
        if enqueued >= remaining:
            skipped += 1
            continue
        await create_check_job(
            session,
            settings=settings,
            publishers=publishers,
            methodology=methodology,
            text=text,
            user_id=row.user_id,
            response_language=row.response_language,
            turn_type=TurnType(row.turn_type),
            source_url=(row.input or {}).get("url"),
            source_file_name=(row.input or {}).get("file_name"),
            source_media_type=(row.input or {}).get("media_type"),
            source_size_bytes=(row.input or {}).get("size_bytes"),
            context=((row.input or {}).get("context") or {}).get("messages"),
            previous_result_id=row.id,
        )
        job = (
            await session.execute(select(JobRow).order_by(JobRow.created_at.desc()).limit(1))
        ).scalar_one()
        job.payload = {
            **(job.payload or {}),
            "recheck": True,
            "recheck_reason": reason,
            "recheck_document_id": document.id,
        }
        enqueued += 1
    return {"enqueued": enqueued, "skipped_budget": skipped}


async def retry_failed_document(
    session: AsyncSession,
    *,
    document: Document,
    version: DocumentVersion,
    settings: Settings,
) -> DocumentWarning | None:
    """Reparse the stored raw bytes of a failed document; return an error warning or None."""
    if not version.raw_bytes:
        return DocumentWarning(code="retry_unavailable", message="No raw content was stored.")
    try:
        text, title = read_file_bytes(
            filename=version.file_path or document.title,
            content_type=version.raw_media_type or "application/octet-stream",
            data=version.raw_bytes,
            settings=settings,
        )
    except (ValueError, OSError) as exc:
        return DocumentWarning(code="parse_warning", message=str(exc)[:500])
    if not text.strip():
        return DocumentWarning(code="parse_warning", message="The retry produced no readable text.")
    document.content_hash = sha256_text(text)
    if title and document.title in {"", "Untitled document"}:
        document.title = title[:500]
    warnings = _warnings(
        content=text,
        language=document.language,
        supported=settings.supported_languages,
        license_=document.license,
        quality=document.source_quality,
        duplicate_of=None,
    )
    document.warnings = [item.model_dump(mode="json") for item in warnings]
    document.state = "warning" if warnings else "ready"
    document.updated_at = utcnow()
    version.content_md = text
    version.content_hash = document.content_hash
    version.size_bytes = len(version.raw_bytes)
    await session.flush()
    return None
