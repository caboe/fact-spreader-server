"""Native check endpoints (PROTOCOL §4). Phase 1: text input, async jobs, minimal SSE."""

from __future__ import annotations

import asyncio
import json
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
from app.db.models import IdempotencyKey
from app.db.models import Job as JobRow
from app.db.session import get_session
from app.services.auth import Principal, require_permission
from app.services.checks import (
    create_check_job,
    job_to_api,
    load_response,
    request_hash,
)

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
    _validate_phase1_request(body, request.app.state.settings)
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
        response = await load_response(session, job.result_id)
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

    async def stream() -> AsyncIterator[bytes]:
        session_factory = request.app.state.db.session_factory
        last_state: str | None = None
        sequence = 0
        for _ in range(600):
            async with session_factory() as poll_session:
                row = await poll_session.get(JobRow, job_id)
                if row is None:
                    yield _sse("error", {"code": "job_not_found"}, sequence)
                    return
                api_job = job_to_api(row)
                if api_job.state != last_state:
                    sequence += 1
                    last_state = api_job.state
                    yield _sse("state", api_job.model_dump(mode="json"), sequence)
                if api_job.state in {
                    JobState.DONE.value,
                    JobState.FAILED.value,
                    JobState.CANCELLED.value,
                }:
                    sequence += 1
                    yield _sse(
                        "done",
                        {
                            "job": api_job.model_dump(mode="json"),
                            "result_id": api_job.result_id,
                        },
                        sequence,
                    )
                    return
            await asyncio.sleep(1.0)
        yield b": stream_timeout\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def _load_owned_job(session: AsyncSession, job_id: str, principal: Principal) -> JobRow:
    job = await session.get(JobRow, job_id)
    if job is None:
        raise AppError(404, "not_found", "The job does not exist.")
    if job.user_id != principal.user_id and not principal.has("quality:read"):
        raise AppError(404, "not_found", "The job does not exist.")
    return job


def _validate_phase1_request(body: CheckRequest, settings: Settings) -> None:
    text = body.input.text
    if body.input.type != "text":
        raise AppError(
            422,
            "input_type_not_supported",
            "Phase 1 accepts text input only; file, URL and image arrive in Phase 2.",
        )
    if text is None or not text.strip():
        raise AppError(422, "empty_input", "The input text is empty.")
    if len(text) > settings.max_text_chars:
        raise AppError(413, "payload_too_large", "The input text is too long.")
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
    if (
        body.persona_id is not None
        or body.render_model_id is not None
        or body.output_format == "persona"
    ):
        raise AppError(
            422,
            "rendering_not_available",
            "Persona rendering arrives in Phase 2.",
        )
    request_language = body.response_language
    if request_language is not None and request_language not in settings.supported_languages:
        raise AppError(
            422,
            "unsupported_response_language",
            f"Response language {request_language!r} is not supported.",
        )


def _sse(event: str, data: dict[str, object], sequence: int) -> bytes:
    return (
        f"id: {sequence}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    ).encode()
