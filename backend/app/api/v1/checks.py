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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import CheckRequest, JobAccepted, JobEnvelope
from app.contracts.enums import JobState, TurnType
from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import new_id, normalize_text, utcnow
from app.db.models import IdempotencyKey, JobEvent
from app.db.models import Job as JobRow
from app.db.session import get_session
from app.services.auth import Principal, require_permission
from app.services.checks import (
    create_check_job,
    job_to_api,
    load_response,
    request_hash,
)
from app.services.input_reader import UrlFetchError, UrlSafetyError, fetch_readable

router = APIRouter(prefix="/v1", tags=["checks"])
ClaimsSubmit = Annotated[Principal, Depends(require_permission("claims:submit"))]


@router.post("/factcheck", status_code=202)
async def create_check(
    body: CheckRequest,
    request: Request,
    principal: ClaimsSubmit,
    session: Annotated[AsyncSession, Depends(get_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> Response:
    _validate_phase1_request(
        body,
        request.app.state.settings,
        [persona.id for persona in request.app.state.personas.enabled()],
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
    else:
        normalized = normalize_text(body.input.text or "")
    payload_for_hash = body.model_dump(mode="json")
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
        turn_type=body.turn_type or TurnType.NEW_CLAIM,
        source_url=source_url,
        persona_id=body.persona_id,
        render_model_id=body.render_model_id,
        output_format=body.output_format.value,
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
    body: CheckRequest, settings: Settings, request_personas: list[str]
) -> None:
    text = body.input.text
    if body.input.type not in {"text", "url"}:
        raise AppError(
            422,
            "input_type_not_supported",
            "This Phase 2 surface accepts text and URL input; file and image uploads are next.",
        )
    if body.input.type == "text":
        if text is None or not text.strip():
            raise AppError(422, "empty_input", "The input text is empty.")
        if len(text) > settings.max_text_chars:
            raise AppError(413, "payload_too_large", "The input text is too long.")
    elif not body.input.url:
        raise AppError(422, "invalid_input", "A URL input requires a url.")
    if body.context:
        raise AppError(
            422,
            "context_not_supported",
            "Conversation context is added in Phase 2.",
        )
    if body.mode == "sync" or body.fast:
        raise AppError(
            422,
            "fast_mode_not_available",
            "The synchronous/fast mode arrives in Phase 3.",
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
