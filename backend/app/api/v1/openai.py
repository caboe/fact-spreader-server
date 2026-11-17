"""OpenAI-compatible fact-check surface (PROTOCOL §6).

The adapter is deliberately thin: it validates the OpenAI body, resolves the model to a
persona, creates the same durable check job as the native endpoint, waits for the checked
result, and only then emits the narrative. The narrative is never streamed before the
consistency check.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import CheckResponse
from app.contracts.enums import JobState, TurnType
from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import normalize_text
from app.db.models import Job as JobRow
from app.db.models import UsageEvent
from app.db.session import get_session
from app.llm.client import LLMError
from app.rendering import render_substance_text
from app.services.auth import Principal, authenticate
from app.services.checks import create_check_job, load_response
from app.services.personas import PersonaRegistry

router = APIRouter(prefix="/v1", tags=["openai"])

_MODEL_CREATED = 1763334000


class OpenAIAuthError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        self.status = status
        self.code = code
        self.message = message


async def openai_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    try:
        principal = await authenticate(request, session)
    except AppError as exc:
        raise OpenAIAuthError(exc.status, exc.code, exc.detail) from exc
    if not principal.has("claims:submit"):
        raise OpenAIAuthError(403, "permission_denied", "The credential needs claims:submit.")
    return principal


class OpenAIMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str
    content: str


class StreamOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    include_usage: bool = False


class OpenAIChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    messages: list[OpenAIMessage]
    stream: bool = False
    stream_options: StreamOptions | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    temperature: float | None = None
    user: str | None = None
    factcheck: dict[str, Any] | None = None


class _JobFailure(RuntimeError):
    pass


def _error(
    status: int, code: str, message: str, kind: str = "invalid_request_error"
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": kind, "code": code, "param": None}},
    )


def _parse_factcheck(extension: dict[str, Any] | None) -> dict[str, Any]:
    if extension is None:
        return {}
    allowed = {
        "persona_id",
        "render_model_id",
        "output_format",
        "response_language",
        "include_passages",
        "domain_hint",
        "fast",
        "summary",
    }
    unknown = sorted(set(extension) - allowed)
    if unknown:
        raise ValueError(f"unsupported factcheck fields: {', '.join(unknown)}")
    if extension.get("fast"):
        raise ValueError("fast mode arrives in Phase 3")
    if extension.get("summary"):
        raise ValueError("research mode is not part of this surface yet")
    return extension


def _resolve_persona(
    *,
    model: str,
    extension: dict[str, Any],
    personas: PersonaRegistry,
) -> tuple[str | None, str]:
    """Return (persona_id, output_format)."""
    if model == "factcheck:none":
        persona_id = None
    elif model == "factcheck":
        persona_id = extension.get("persona_id") or personas.default_id
    elif model.startswith("factcheck:"):
        persona_id = model.split(":", 1)[1]
    else:
        raise LookupError(model)
    requested = extension.get("persona_id")
    if requested and persona_id and requested != persona_id:
        raise ValueError("the model and factcheck.persona_id name different personas")
    output_format = str(
        extension.get("output_format") or ("persona" if persona_id else "substance")
    )
    if output_format not in {"substance", "persona", "compact"}:
        raise ValueError(f"unsupported output_format {output_format!r}")
    if output_format == "persona" and persona_id is None:
        raise ValueError("output_format=persona requires a persona")
    if persona_id is None:
        output_format = "substance"
    if persona_id and personas.get(persona_id) is None:
        raise ValueError(f"unknown persona {persona_id!r}")
    return persona_id, output_format


async def _aggregate_usage(session: AsyncSession, job_id: str) -> dict[str, int]:
    tokens_in, tokens_out = (
        await session.execute(
            select(
                func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                func.coalesce(func.sum(UsageEvent.tokens_out), 0),
            ).where(UsageEvent.request_id == job_id)
        )
    ).one()
    return {
        "prompt_tokens": int(tokens_in),
        "completion_tokens": int(tokens_out),
        "total_tokens": int(tokens_in) + int(tokens_out),
    }


async def _wait_for_job(
    session_factory: Any, job_id: str, *, wait_seconds: float = 240.0
) -> tuple[JobRow, CheckResponse]:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        async with session_factory() as session:
            job = await session.get(JobRow, job_id)
            if job is None:
                raise _JobFailure("the job disappeared")
            if job.state == JobState.FAILED.value:
                code = (job.error or {}).get("code", "pipeline_error")
                raise _JobFailure(str(code))
            if job.state == JobState.DONE.value and job.result_id:
                payload = job.payload or {}
                response = await load_response(
                    session, job.result_id, persona_id=payload.get("persona_id")
                )
                if response is None:
                    raise _JobFailure("the result disappeared")
                return job, response
        await asyncio.sleep(0.7)
    raise TimeoutError("the check did not finish in time")


def _content_for(response: CheckResponse, persona_id: str | None) -> tuple[str, str | None]:
    result = response.result
    if result.status == "refused":
        return result.overall_explanation or "This input cannot be checked.", "content_filter"
    if persona_id and response.rendering is not None:
        return response.rendering.text, None
    if response.compact is not None and response.rendering is None:
        return render_substance_text(result, result.response_language), None
    return render_substance_text(result, result.response_language), None


def _factcheck_object(response: CheckResponse, *, job_id: str) -> dict[str, Any]:
    return {
        "result": response.result.model_dump(mode="json", by_alias=True),
        "rendering": (
            response.rendering.model_dump(mode="json", by_alias=True)
            if response.rendering
            else None
        ),
        "compact": response.compact.model_dump(mode="json", by_alias=True)
        if response.compact
        else None,
        "job_id": job_id,
        "full_result_pending": False,
    }


@router.get("/models")
async def openai_models(
    request: Request,
    principal: Annotated[Principal, Depends(openai_principal)],
) -> dict[str, Any]:
    personas: PersonaRegistry = request.app.state.personas
    models: list[dict[str, Any]] = [
        {
            "id": "factcheck",
            "object": "model",
            "created": _MODEL_CREATED,
            "owned_by": "fact-spreader",
            "factcheck": {
                "kind": "check",
                "persona_id": personas.default_id,
                "output_formats": ["substance", "persona"],
                "fast": False,
                "streaming": True,
            },
        }
    ]
    for persona in personas.enabled():
        models.append(
            {
                "id": f"factcheck:{persona.id}",
                "object": "model",
                "created": _MODEL_CREATED,
                "owned_by": "fact-spreader",
                "factcheck": {
                    "kind": "check",
                    "persona_id": persona.id,
                    "output_formats": ["substance", "persona"],
                    "fast": False,
                    "streaming": True,
                },
            }
        )
    models.append(
        {
            "id": "factcheck:none",
            "object": "model",
            "created": _MODEL_CREATED,
            "owned_by": "fact-spreader",
            "factcheck": {
                "kind": "substance",
                "persona_id": None,
                "output_formats": ["substance", "compact"],
                "fast": False,
                "streaming": True,
            },
        }
    )
    return {"object": "list", "data": models}


@router.post("/chat/completions", response_model=None)
async def chat_completions(
    request: Request,
    principal: Annotated[Principal, Depends(openai_principal)],
) -> JSONResponse | StreamingResponse:
    try:
        raw = await request.json()
    except ValueError:
        return _error(400, "invalid_json", "The request body is not valid JSON.")
    try:
        body = OpenAIChatRequest.model_validate(raw)
    except ValidationError as exc:
        return _error(400, "unsupported_parameter", _validation_message(exc))
    try:
        extension = _parse_factcheck(body.factcheck)
        persona_id, output_format = _resolve_persona(
            model=body.model,
            extension=extension,
            personas=request.app.state.personas,
        )
    except LookupError:
        return _error(404, "model_not_found", f"Unknown model {body.model!r}.")
    except ValueError as exc:
        return _error(400, "unsupported_parameter", str(exc))
    if not body.messages or body.messages[-1].role != "user":
        return _error(400, "invalid_messages", "The last message must be from the user.")
    if any(message.role not in {"system", "user", "assistant"} for message in body.messages):
        return _error(400, "invalid_messages", "Unsupported message role.")
    text = normalize_text(body.messages[-1].content)
    context = [{"role": message.role, "content": message.content} for message in body.messages[:-1]]
    turn_type = TurnType.NEW_CLAIM
    if context:
        turn_type = (
            TurnType.REPEATED_CLAIM
            if any(
                message["role"] == "user" and normalize_text(message["content"]) == text
                for message in context
            )
            else TurnType.FOLLOW_UP_CLAIM
        )
    if not text:
        return _error(400, "empty_input", "The user message is empty.")
    settings: Settings = request.app.state.settings
    if len(text) > settings.max_text_chars:
        return _error(400, "input_too_long", "The user message is too long.")
    if body.stream:
        return await _stream_response(
            request=request,
            principal=principal,
            body=body,
            text=text,
            persona_id=persona_id,
            output_format=output_format,
            context=context,
            turn_type=turn_type,
        )
    return await _non_streaming_response(
        request=request,
        principal=principal,
        body=body,
        text=text,
        persona_id=persona_id,
        output_format=output_format,
        context=context,
        turn_type=turn_type,
    )


async def _create_job(
    request: Request,
    principal: Principal,
    *,
    body: OpenAIChatRequest,
    text: str,
    persona_id: str | None,
    output_format: str,
    context: list[dict[str, str]],
    turn_type: TurnType,
) -> tuple[JobRow, str]:
    session_factory = request.app.state.db.session_factory
    async with session_factory() as session:
        job, _moderation = await create_check_job(
            session,
            settings=request.app.state.settings,
            publishers=request.app.state.publishers,
            methodology=request.app.state.methodology,
            text=text,
            user_id=principal.user_id,
            response_language=body.factcheck.get("response_language") if body.factcheck else None,
            turn_type=turn_type,
            context=context,
            persona_id=persona_id,
            render_model_id=body.factcheck.get("render_model_id") if body.factcheck else None,
            output_format=output_format,
            render_max_tokens=body.max_completion_tokens or body.max_tokens or 8000,
            render_temperature=body.temperature if body.temperature is not None else 0.4,
        )
        await session.commit()
        return job, job.id


async def _non_streaming_response(
    *,
    request: Request,
    principal: Principal,
    body: OpenAIChatRequest,
    text: str,
    persona_id: str | None,
    output_format: str,
    context: list[dict[str, str]],
    turn_type: TurnType,
) -> JSONResponse:
    try:
        _job, job_id = await _create_job(
            request,
            principal,
            body=body,
            text=text,
            persona_id=persona_id,
            output_format=output_format,
            context=context,
            turn_type=turn_type,
        )
    except AppError as exc:
        return _error(exc.status, exc.code, exc.detail, _kind_for_status(exc.status))
    except LLMError as exc:
        return _error(exc.status, exc.code, exc.detail, _kind_for_status(exc.status))
    try:
        async with request.app.state.db.session_factory() as session:
            _job, response = await _wait_for_job(
                request.app.state.db.session_factory, job_id, wait_seconds=240
            )
            usage = await _aggregate_usage(session, job_id)
    except _JobFailure as exc:
        return _error(502, "pipeline_error", f"The check failed: {exc}")
    except TimeoutError:
        return _error(504, "job_timeout", "The check did not finish in time.")
    content, finish_reason = _content_for(response, persona_id)
    model_name = body.model
    if output_format == "compact" and response.compact is not None:
        content = response.compact.bottom_line
        finish_reason = "stop"
    choices: list[dict[str, Any]] = [
        {
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": finish_reason or "stop",
        }
    ]
    payload: dict[str, Any] = {
        "id": f"chatcmpl-{job_id}",
        "object": "chat.completion",
        "created": int(datetime.now(UTC).timestamp()),
        "model": model_name,
        "choices": choices,
        "usage": usage,
        "factcheck": _factcheck_object(response, job_id=job_id),
    }
    return JSONResponse(content=payload)


async def _stream_response(
    *,
    request: Request,
    principal: Principal,
    body: OpenAIChatRequest,
    text: str,
    persona_id: str | None,
    output_format: str,
    context: list[dict[str, str]],
    turn_type: TurnType,
) -> JSONResponse | StreamingResponse:
    try:
        _job, job_id = await _create_job(
            request,
            principal,
            body=body,
            text=text,
            persona_id=persona_id,
            output_format=output_format,
            context=context,
            turn_type=turn_type,
        )
    except AppError as exc:
        return _error(exc.status, exc.code, exc.detail, _kind_for_status(exc.status))
    except LLMError as exc:
        return _error(exc.status, exc.code, exc.detail, _kind_for_status(exc.status))
    session_factory = request.app.state.db.session_factory
    include_usage = bool(body.stream_options and body.stream_options.include_usage)

    async def events() -> AsyncIterator[bytes]:
        started = time.monotonic()
        last_keepalive = started
        try:
            while time.monotonic() - started < 240:
                async with session_factory() as session:
                    job = await session.get(JobRow, job_id)
                    if job is None:
                        yield _chunk_error("job_not_found", "The check job disappeared.")
                        return
                    if job.state == JobState.FAILED.value:
                        yield _chunk_error("pipeline_error", "The check failed.")
                        return
                    if job.state == JobState.DONE.value and job.result_id:
                        response = await load_response(
                            session, job.result_id, persona_id=persona_id
                        )
                        if response is None:
                            yield _chunk_error("result_missing", "The result disappeared.")
                            return
                        content, finish_reason = _content_for(response, persona_id)
                        if output_format == "compact" and response.compact is not None:
                            content = response.compact.bottom_line
                        usage = await _aggregate_usage(session, job_id)
                        factcheck = _factcheck_object(response, job_id=job_id)
                        first = _chunk(
                            job_id,
                            body.model,
                            delta={},
                            factcheck=factcheck,
                        )
                        yield _sse(first)
                        for piece in _text_pieces(content):
                            yield _sse(_chunk(job_id, body.model, delta={"content": piece}))
                        final = _chunk(
                            job_id,
                            body.model,
                            delta={},
                            finish_reason=finish_reason or "stop",
                            usage=usage if include_usage else None,
                            factcheck={"rendering": factcheck["rendering"]},
                        )
                        yield _sse(final)
                        yield b"data: [DONE]\n\n"
                        return
                now = time.monotonic()
                if now - last_keepalive >= 15:
                    last_keepalive = now
                    yield b": keepalive\n\n"
                await asyncio.sleep(0.7)
            yield _chunk_error("job_timeout", "The check did not finish in time.")
        except Exception:
            yield _chunk_error("internal_error", "The stream failed.")

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


def _text_pieces(text: str, size: int = 80) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)] or [""]


def _chunk(
    job_id: str,
    model: str,
    *,
    delta: dict[str, Any],
    finish_reason: str | None = None,
    usage: dict[str, int] | None = None,
    factcheck: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": f"chatcmpl-{job_id}",
        "object": "chat.completion.chunk",
        "created": int(datetime.now(UTC).timestamp()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    if usage is not None:
        payload["usage"] = usage
    if factcheck is not None:
        payload["factcheck"] = factcheck
    return payload


def _sse(payload: dict[str, Any]) -> bytes:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _chunk_error(code: str, message: str) -> bytes:
    payload = {"error": {"code": code, "message": message}}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode()


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        parts.append(f"{location}: {error['msg']}")
    return "Unsupported or invalid parameter: " + "; ".join(parts)


def _kind_for_status(status: int) -> str:
    if status == 429:
        return "rate_limit_error"
    if status >= 500:
        return "server_error"
    if status in {401, 403}:
        return "authentication_error"
    return "invalid_request_error"
