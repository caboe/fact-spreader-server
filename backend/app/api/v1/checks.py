"""Native check endpoints (PROTOCOL §4). Phase 1: text input, async jobs, minimal SSE."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from app.contracts.api import CheckRequest, JobAccepted, JobEnvelope
from app.contracts.enums import JobState, TurnType
from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import new_id, normalize_text, utcnow
from app.db.models import IdempotencyKey, JobEvent
from app.db.models import Job as JobRow
from app.db.session import get_session
from app.llm.client import LLMClient, LLMError
from app.services.auth import Principal, require_permission
from app.services.checks import (
    create_check_job,
    job_to_api,
    load_response,
    request_hash,
)
from app.services.fast import run_fast
from app.services.image_input import extract_image_text, prepare_image
from app.services.input_reader import (
    UrlFetchError,
    UrlSafetyError,
    fetch_readable,
    read_file_bytes,
)
from app.services.limits import enforce_limits

router = APIRouter(prefix="/v1", tags=["checks"])

_CHECK_REQUEST_SCHEMA = CheckRequest.model_json_schema()
_CHECK_BODY_OPENAPI = {
    "required": True,
    "content": {
        "application/json": {"schema": _CHECK_REQUEST_SCHEMA},
        "multipart/form-data": {
            "schema": {
                "type": "object",
                "required": ["payload", "file"],
                "properties": {
                    "payload": {
                        "type": "string",
                        "description": "JSON CheckRequest with input.type=file",
                    },
                    "file": {"type": "string", "format": "binary"},
                },
            }
        },
    },
}
ClaimsSubmit = Annotated[Principal, Depends(require_permission("claims:submit"))]


@router.post("/factcheck", status_code=202, openapi_extra={"requestBody": _CHECK_BODY_OPENAPI})
async def create_check(
    request: Request,
    principal: ClaimsSubmit,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Response:
    content_type = request.headers.get("content-type", "")
    is_multipart = content_type.startswith("multipart/form-data")
    upload_name: str | None = None
    upload_media: str | None = None
    upload_size: int | None = None
    source_image = False
    file_text: str | None = None
    try:
        if is_multipart:
            form = await request.form()
            payload_part = form.get("payload")
            if not isinstance(payload_part, str):
                raise AppError(422, "invalid_input", "A multipart check needs a payload part.")
            body = CheckRequest.model_validate_json(payload_part)
            file_part = None
            for key, value in form.multi_items():
                if key in {"file", "files"} and isinstance(value, UploadFile):
                    file_part = value
                    break
            if file_part is None:
                raise AppError(422, "invalid_input", "A multipart check needs one file.")
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
                try:
                    prepared = prepare_image(data, media, settings)
                except UrlFetchError as exc:
                    raise AppError(422, "file_parse_failed", str(exc)) from exc
                try:
                    vision = await extract_image_text(
                        LLMClient(settings, consumer="vision"),
                        prepared,
                        user_id=principal.user_id,
                    )
                except LLMError as exc:
                    raise AppError(
                        exc.status if exc.status in {429, 503} else 502,
                        exc.code,
                        exc.detail,
                    ) from exc
                file_text = (
                    "Image text:\n" + vision.text + "\n\nImage description:\n" + vision.description
                )
                source_image = True
                upload_media = media
            else:
                try:
                    file_text, _title = read_file_bytes(
                        filename=filename, content_type=media, data=data, settings=settings
                    )
                except UrlFetchError as exc:
                    raise AppError(422, "file_parse_failed", str(exc)) from exc
                upload_media = media
            if not file_text.strip():
                raise AppError(422, "empty_input", "The uploaded file has no readable text.")
            upload_name = filename
            upload_size = len(data)
        else:
            raw = await request.json()
            body = CheckRequest.model_validate(raw)
    except ValidationError as exc:
        raise AppError(
            422, "validation_error", str(exc.errors()[0].get("msg", "invalid body"))
        ) from exc
    except ValueError as exc:
        raise AppError(400, "invalid_json", "The request body is not valid JSON.") from exc
    _validate_phase1_request(
        body,
        request.app.state.settings,
        [persona.id for persona in request.app.state.personas.enabled()],
        allow_file=is_multipart,
    )
    await enforce_limits(
        session,
        request.app.state.settings,
        principal.user_id,
        text_chars=len(body.input.text or "") if body.input.text else None,
        file_bytes=upload_size,
    )
    source_url: str | None = None
    if body.input.type == "url":
        assert body.input.url is not None  # validated in _validate_phase1_request
        try:
            page = await fetch_readable(body.input.url, request.app.state.settings)
        except UrlSafetyError as exc:
            raise AppError(422, "unsafe_url", str(exc)) from exc
        except UrlFetchError as exc:
            raise AppError(502, "url_fetch_failed", str(exc)) from exc
        normalized = normalize_text(page.text[: request.app.state.settings.max_text_chars])
        source_url = page.url
    elif body.input.type in {"file", "image"}:
        assert file_text is not None
        normalized = normalize_text(file_text[: request.app.state.settings.max_text_chars])
    else:
        normalized = normalize_text(body.input.text or "")
    payload_for_hash = {
        **body.model_dump(mode="json"),
        "upload": {
            "name": upload_name,
            "media_type": upload_media,
            "size": upload_size,
        },
    }
    if idempotency_key:
        if len(idempotency_key) > 128:
            raise AppError(422, "invalid_idempotency_key", "Idempotency-Key is too long.")
        existing = (
            await session.execute(
                select(IdempotencyKey).where(
                    IdempotencyKey.principal_id == principal.principal_id,
                    IdempotencyKey.key == idempotency_key,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            if existing.expires_at < utcnow():
                await session.delete(existing)
            elif existing.request_hash != request_hash(payload_for_hash):
                raise AppError(
                    422,
                    "idempotency_key_reused",
                    "This Idempotency-Key was used with a different request body.",
                )
            else:
                return JSONResponse(
                    status_code=existing.status_code,
                    content=existing.response,
                    headers={"Idempotency-Key": idempotency_key},
                )
    job_row, _moderation = await create_check_job(
        session,
        settings=request.app.state.settings,
        publishers=request.app.state.publishers,
        methodology=request.app.state.methodology,
        text=normalized,
        user_id=principal.user_id,
        response_language=body.response_language,
        turn_type=body.turn_type
        or (TurnType.FOLLOW_UP_CLAIM if body.context else TurnType.NEW_CLAIM),
        source_url=source_url,
        source_file_name=upload_name,
        source_media_type=upload_media,
        source_size_bytes=upload_size,
        source_image=source_image,
        context=[item.model_dump() for item in body.context],
        persona_id=body.persona_id,
        render_model_id=body.render_model_id,
        output_format=body.output_format.value,
    )
    if body.fast:
        if job_row.state == JobState.DONE.value and job_row.result_id:
            response = await load_response(session, job_row.result_id, persona_id=body.persona_id)
            if response is None:
                raise AppError(404, "not_found", "The result does not exist.")
            await session.commit()
            return JSONResponse(
                status_code=200,
                content=response.model_dump(mode="json", by_alias=True),
                headers={
                    "ETag": f'"{response.result.id}:{response.result.version}"',
                    "X-Result-Preliminary": "false",
                },
            )
        fast_response = await run_fast(
            session,
            settings=request.app.state.settings,
            publishers=request.app.state.publishers,
            methodology=request.app.state.methodology,
            language=request.app.state.language,
            job=job_row,
            text=normalized,
            response_language=body.response_language,
        )
        await session.commit()
        return JSONResponse(
            status_code=200,
            content=fast_response.model_dump(mode="json", by_alias=True),
            headers={
                "ETag": f'"{fast_response.result.id}:1"',
                "X-Result-Preliminary": "true",
                "X-Full-Result-Job": job_row.id,
            },
        )
    await session.commit()
    job = job_to_api(job_row)
    accepted = JobAccepted(job=job, poll_after_ms=job.poll_after_ms)
    response_payload = accepted.model_dump(mode="json")
    if idempotency_key:
        session.add(
            IdempotencyKey(
                id=new_id("idem"),
                principal_id=principal.principal_id,
                key=idempotency_key,
                request_hash=request_hash(payload_for_hash),
                status_code=202,
                response=response_payload,
                created_at=utcnow(),
                expires_at=utcnow() + timedelta(hours=24),
            )
        )
        await session.commit()
    return JSONResponse(
        status_code=202,
        content=response_payload,
        headers={
            "Location": f"/v1/factcheck/{job.id}",
            **({"Idempotency-Key": idempotency_key} if idempotency_key else {}),
        },
    )


@router.get("/factcheck/{job_id}", response_model=JobEnvelope)
async def get_check(
    job_id: str,
    request: Request,
    principal: ClaimsSubmit,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    job = await _load_owned_job(session, job_id, principal)
    envelope = JobEnvelope(job=job_to_api(job), result=None)
    if job.state in {JobState.FAILED.value, JobState.CANCELLED.value}:
        return JSONResponse(
            status_code=200,
            content=envelope.model_dump(mode="json"),
        )
    if job.result_id:
        response = await load_response(
            session,
            job.result_id,
            persona_id=(job.payload or {}).get("persona_id"),
        )
        envelope = JobEnvelope(job=job_to_api(job), result=response)
        etag = f'"{job.result_id}:{response.result.version if response else 1}"'
        if request.headers.get("If-None-Match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return JSONResponse(
            status_code=200,
            content=envelope.model_dump(mode="json"),
            headers={"ETag": etag},
        )
    return JSONResponse(status_code=202, content=envelope.model_dump(mode="json"))


@router.get("/factcheck/{job_id}/events")
async def check_events(
    job_id: str,
    request: Request,
    principal: ClaimsSubmit,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StreamingResponse:
    await _load_owned_job(session, job_id, principal)
    last_event_id = request.headers.get("Last-Event-ID", "0")
    try:
        last_sequence = max(0, int(last_event_id))
    except ValueError:
        last_sequence = 0

    async def stream() -> AsyncIterator[bytes]:
        nonlocal last_sequence
        session_factory = request.app.state.db.session_factory
        last_state: str | None = None
        keepalive_at = time.monotonic()
        deadline = keepalive_at + 600
        while time.monotonic() < deadline:
            emitted = False
            async with session_factory() as poll_session:
                events = (
                    (
                        await poll_session.execute(
                            select(JobEvent)
                            .where(JobEvent.job_id == job_id, JobEvent.seq > last_sequence)
                            .order_by(JobEvent.seq)
                        )
                    )
                    .scalars()
                    .all()
                )
                for event in events:
                    last_sequence = event.seq
                    emitted = True
                    yield _sse_event(event.event_type, event.data, event.seq)
                row = await poll_session.get(JobRow, job_id)
                if row is None:
                    yield _sse_event("error", {"code": "job_not_found"})
                    return
                api_job = job_to_api(row)
                if api_job.state != last_state:
                    last_state = api_job.state
                    emitted = True
                    yield _sse_event("state", api_job.model_dump(mode="json"))
                if api_job.state in {
                    JobState.DONE.value,
                    JobState.FAILED.value,
                    JobState.CANCELLED.value,
                }:
                    if api_job.result_id:
                        response = await load_response(
                            poll_session,
                            api_job.result_id,
                            persona_id=(row.payload or {}).get("persona_id"),
                        )
                        if response is not None:
                            yield _sse_event(
                                "result", response.model_dump(mode="json", by_alias=True)
                            )
                    yield _sse_event(
                        "done",
                        {
                            "job": api_job.model_dump(mode="json"),
                            "result_id": api_job.result_id,
                        },
                    )
                    return
            if not emitted and time.monotonic() - keepalive_at >= 15:
                keepalive_at = time.monotonic()
                yield b": keepalive\n\n"
            await asyncio.sleep(0.8)
        yield b": stream_timeout\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.delete("/factcheck/{job_id}", status_code=204)
async def cancel_check(
    job_id: str,
    principal: ClaimsSubmit,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    job = await _load_owned_job(session, job_id, principal)
    if job.state == JobState.QUEUED.value:
        job.state = JobState.CANCELLED.value
        job.finished_at = utcnow()
        await session.commit()
        return Response(status_code=204)
    raise AppError(409, "job_not_cancellable", "Only a queued job can be cancelled.")


async def _load_owned_job(session: AsyncSession, job_id: str, principal: Principal) -> JobRow:
    job = await session.get(JobRow, job_id)
    if job is None:
        raise AppError(404, "not_found", "The job does not exist.")
    if job.user_id != principal.user_id and not principal.has("quality:read"):
        raise AppError(404, "not_found", "The job does not exist.")
    return job


def _validate_phase1_request(
    body: CheckRequest,
    settings: Settings,
    request_personas: list[str],
    *,
    allow_file: bool = False,
) -> None:
    text = body.input.text
    allowed_types = {"text", "url"} | ({"file", "image"} if allow_file else set())
    if body.input.type not in allowed_types:
        raise AppError(
            422,
            "input_type_not_supported",
            "The input type is not supported by this endpoint.",
        )
    if body.input.type in {"file", "image"}:
        if not allow_file:
            raise AppError(
                422,
                "input_type_not_supported",
                "A file or image input must use the multipart form.",
            )
    elif body.input.type == "text":
        if text is None or not text.strip():
            raise AppError(422, "empty_input", "The input text is empty.")
        if len(text) > settings.max_text_chars:
            raise AppError(413, "payload_too_large", "The input text is too long.")
    elif body.input.type == "url" and not body.input.url:
        raise AppError(422, "invalid_input", "A URL input requires a url.")
    if body.mode == "sync" and not body.fast:
        raise AppError(422, "sync_requires_fast", "Sync mode requires fast=true.")
    if body.fast:
        if body.input.type in {"file", "image"}:
            pass
        elif body.input.type != "text" or len(body.input.text or "") > 5000:
            raise AppError(
                422,
                "invalid_input",
                "Fast mode accepts text up to 5,000 characters or one image.",
            )
    if body.output_format == "persona" and body.persona_id is None:
        raise AppError(
            422,
            "persona_required",
            "output_format=persona requires a persona_id.",
        )
    if body.persona_id is not None and body.persona_id not in request_personas:
        raise AppError(422, "unknown_persona", f"Unknown persona {body.persona_id!r}.")
    if body.render_model_id is not None and body.persona_id is None:
        raise AppError(
            422,
            "persona_required",
            "render_model_id only applies to a persona rendering.",
        )
    request_language = body.response_language
    if request_language is not None and request_language not in settings.supported_languages:
        raise AppError(
            422,
            "unsupported_response_language",
            f"Response language {request_language!r} is not supported.",
        )


def _sse_event(event: str, data: dict[str, object], sequence: int | None = None) -> bytes:
    identifier = f"id: {sequence}\n" if sequence is not None else ""
    return (
        f"{identifier}event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    ).encode()
