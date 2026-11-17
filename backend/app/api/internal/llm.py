"""Internal OpenAI-compatible LLM gateway (PROTOCOL §12, hard invariant 8).

There is no other path to a provider. The gateway resolves a stable alias, applies the
data-flow rule and the budget, calls the provider with its decrypted key, records a
content-free usage event and returns the provider's OpenAI-shaped response.

LightRAG uses this endpoint with ``fs-extract`` and ``fs-embedding``; the pipeline uses the
role aliases. A forbidden call fails explicitly or uses a configured fallback; it is never
silently sent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.http import CircuitOpenError, OutboundHTTP
from app.core.ids import new_id, utcnow
from app.core.security import SecretBox, constant_time_equals
from app.db.models import Instance, ModelRecord, Provider, Setting, UsageEvent, User
from app.db.session import get_session
from app.llm.aliases import ALL_ALIASES

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal/llm/v1", tags=["internal-llm"])

_ROLE_ALIASES = {
    "role:chat": "fs-chat",
    "role:extract": "fs-extract",
    "role:verify": "fs-verify",
    "role:audit": "fs-audit",
    "role:moderation": "fs-moderation",
    "role:embedding": "fs-embedding",
    "role:vision": "fs-vision",
}


@dataclass(frozen=True)
class InternalCall:
    consumer: str
    data_classes: frozenset[str]
    user_id: str | None
    purpose: str
    request_id: str


def _openai_error(
    status: int, message: str, code: str, kind: str = "invalid_request_error"
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "type": kind, "code": code, "param": None}},
    )


async def internal_call(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> InternalCall:
    settings: Settings = request.app.state.settings
    expected = settings.internal_llm_key.get_secret_value()
    lightrag_key = settings.lightrag_internal_key.get_secret_value() or expected
    if not expected:
        raise _InternalAuthError(503, "internal_key_not_configured")
    authorization = request.headers.get("Authorization", "")
    if not authorization.lower().startswith("bearer "):
        raise _InternalAuthError(401, "internal_auth_required")
    token = authorization[7:].strip()
    if constant_time_equals(token, lightrag_key):
        # LightRAG has one internal key for all its calls and cannot add our consumer
        # headers. Its calls are attributed to the service, not to a single document
        # (PROTOCOL §12.2 allows exactly this).
        return InternalCall(
            consumer="lightrag",
            data_classes=frozenset({"own_corpus"}),
            user_id=None,
            purpose="lightrag",
            request_id=request.headers.get("X-Request-Id", "")[:80],
        )
    if not constant_time_equals(token, expected):
        raise _InternalAuthError(403, "internal_auth_failed")
    return InternalCall(
        consumer=request.headers.get("X-FS-Consumer", "unknown")[:40],
        data_classes=frozenset(
            part.strip()
            for part in request.headers.get("X-FS-Data-Classes", "").split(",")
            if part.strip()
        ),
        user_id=request.headers.get("X-FS-User-Id") or None,
        purpose=request.headers.get("X-FS-Purpose", "unknown")[:40],
        request_id=request.headers.get("X-Request-Id", "")[:80],
    )


class _InternalAuthError(Exception):
    def __init__(self, status: int, code: str) -> None:
        self.status = status
        self.code = code


async def _resolve_model(session: AsyncSession, alias: str) -> tuple[ModelRecord, Provider]:
    alias = _ROLE_ALIASES.get(alias, alias)
    row = (
        await session.execute(
            select(ModelRecord, Provider)
            .join(Provider, Provider.id == ModelRecord.provider_id)
            .where(ModelRecord.gateway_alias == alias)
        )
    ).first()
    if row is None or not row[0].enabled or not row[1].enabled:
        raise LookupError(f"unknown or disabled gateway alias {alias!r}")
    return row


async def _budget_error(
    session: AsyncSession, settings: Settings, user_id: str | None, model: ModelRecord
) -> JSONResponse | None:
    # A zero-cost local model spends nothing: blocking it would disable the free
    # semantic-cache embedding while the paid budget is exhausted.
    if model.input_cost_per_mtok == 0 and model.output_cost_per_mtok == 0:
        return None
    now = utcnow()
    month_start = datetime(now.year, now.month, 1, tzinfo=UTC)
    instance = (await session.execute(select(Instance).limit(1))).scalar_one_or_none()
    if instance is None:
        return _openai_error(
            503, "The instance is not initialised.", "setup_required", "server_error"
        )
    spent_instance = (
        await session.execute(
            select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
                UsageEvent.created_at >= month_start
            )
        )
    ).scalar_one()
    if Decimal(spent_instance) >= instance.monthly_budget_usd:
        return _budget_response(now)
    role_row = await session.get(Setting, "budgets.roles")
    role_budget: float | None = None
    if role_row is not None and isinstance(role_row.value, dict):
        roles = role_row.value.get("roles")
        if isinstance(roles, dict) and roles.get(model.gateway_alias) is not None:
            role_budget = float(roles[model.gateway_alias])
    if role_budget is not None:
        spent_role = (
            await session.execute(
                select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
                    UsageEvent.created_at >= month_start,
                    UsageEvent.role == model.gateway_alias,
                )
            )
        ).scalar_one()
        if Decimal(spent_role) >= Decimal(str(role_budget)):
            return _budget_response(now)
    if user_id:
        user = await session.get(User, user_id)
        if user is None:
            return _openai_error(
                403, "Unknown user for internal call.", "internal_user_unknown", "permission_error"
            )
        spent_user = (
            await session.execute(
                select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
                    UsageEvent.created_at >= month_start, UsageEvent.user_id == user_id
                )
            )
        ).scalar_one()
        if Decimal(spent_user) >= user.llm_budget_usd:
            return _budget_response(now)
    return None


def _budget_response(now: datetime) -> JSONResponse:
    if now.month == 12:
        reset = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        reset = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    seconds = max(60, int((reset - now).total_seconds()))
    response = _openai_error(
        429,
        "The LLM budget for this month is exhausted. Cached results remain available.",
        "budget_exceeded",
        "rate_limit_error",
    )
    response.headers["Retry-After"] = str(seconds)
    return response


async def _data_flow_policy(session: AsyncSession) -> dict[str, Any]:
    row = await session.get(Setting, "data_flow.allow_external")
    value = row.value if row is not None and isinstance(row.value, dict) else {}
    fallback = value.get("fallback_alias")
    return {
        "allow": bool(value.get("allow", True)),
        "fallback_alias": str(fallback) if fallback else None,
    }


async def _allowed_by_data_flow(
    session: AsyncSession, model: ModelRecord, data_classes: frozenset[str]
) -> bool:
    if model.is_local:
        return True
    policy = await _data_flow_policy(session)
    if policy["allow"]:
        return True
    return not (data_classes & {"user_input", "own_corpus", "figure_description"})


async def _data_flow_fallback(
    session: AsyncSession, data_classes: frozenset[str]
) -> tuple[ModelRecord, Provider] | None:
    """Resolve the configured fallback only when it is itself allowed for this call."""
    policy = await _data_flow_policy(session)
    alias = policy["fallback_alias"]
    if not alias:
        return None
    try:
        model, provider = await _resolve_model(session, alias)
    except LookupError:
        return None
    if model.is_local or await _allowed_by_data_flow(session, model, data_classes):
        return model, provider
    return None


async def _embedding_lock(
    session: AsyncSession, model: ModelRecord, purpose: str
) -> JSONResponse | None:
    lock = await session.get(Setting, "corpus.embedding_model")
    if lock is None:
        session.add(
            Setting(
                key="corpus.embedding_model",
                value={
                    "model_id": model.id,
                    "alias": model.gateway_alias,
                    "dimension": model.embedding_dim,
                },
                updated_at=utcnow(),
            )
        )
        return None
    value = lock.value if isinstance(lock.value, dict) else {}
    if value.get("model_id") == model.id:
        return None
    if purpose == "reindex" and value.get("reindex_override") is True:
        return None
    return _openai_error(
        409,
        "The corpus embedding model is immutable; changing it needs an explicit re-index.",
        "embedding_model_locked",
        "conflict_error",
    )


def _cost(model: ModelRecord, tokens_in: int, tokens_out: int) -> tuple[Decimal, bool]:
    cost = Decimal(tokens_in) * model.input_cost_per_mtok / Decimal(1_000_000) + Decimal(
        tokens_out
    ) * model.output_cost_per_mtok / Decimal(1_000_000)
    return cost.quantize(Decimal("0.000001")), False


def _provider_headers(provider: Provider, settings: Settings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if provider.api_key_enc:
        key = SecretBox(settings.secret_material).decrypt(provider.api_key_enc)
        headers["Authorization"] = f"Bearer {key}"
    return headers


async def _record_usage(
    session: AsyncSession,
    *,
    call: InternalCall,
    model: ModelRecord,
    provider: Provider,
    tokens_in: int,
    tokens_out: int,
    status: int,
    latency_ms: int,
    failure: bool = False,
) -> None:
    cost, estimated = _cost(model, tokens_in, tokens_out)
    session.add(
        UsageEvent(
            id=new_id("evt"),
            request_id=call.request_id or None,
            user_id=call.user_id,
            api_key_id=None,
            consumer=call.consumer,
            role=model.gateway_alias,
            provider=provider.name,
            model=model.model_name,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            cost_estimated=estimated or failure,
            latency_ms=latency_ms,
            status=status,
            data_classes=sorted(call.data_classes),
            created_at=utcnow(),
        )
    )
    try:
        await session.commit()
    except Exception:
        logger.exception("usage event could not be recorded")
        await session.rollback()


@router.get("/models")
async def list_internal_models(
    call: InternalCall = Depends(internal_call),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(ModelRecord, Provider)
            .join(Provider, Provider.id == ModelRecord.provider_id)
            .where(ModelRecord.enabled, Provider.enabled)
        )
    ).all()
    return {
        "object": "list",
        "data": [
            {
                "id": model.gateway_alias,
                "object": "model",
                "owned_by": provider.name,
                "capabilities": model.capabilities,
            }
            for model, provider in rows
            if model.gateway_alias in ALL_ALIASES
        ],
    }


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    call: InternalCall = Depends(internal_call),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    body = await request.json()
    if body.get("stream"):
        return _openai_error(
            400,
            "Streaming through the internal gateway is added in Phase 2.",
            "stream_not_supported",
        )
    alias = str(body.get("model") or "")
    try:
        model, provider = await _resolve_model(session, alias)
    except LookupError as exc:
        return _openai_error(404, str(exc), "model_not_found")
    if "chat" not in (model.capabilities or []):
        return _openai_error(
            422, "The model does not have the chat capability.", "capability_missing"
        )
    if not await _allowed_by_data_flow(session, model, call.data_classes):
        fallback = await _data_flow_fallback(session, call.data_classes)
        if fallback is None:
            return _openai_error(
                403,
                "The data-flow policy forbids sending these data classes to this provider.",
                "data_flow_blocked",
                "permission_error",
            )
        model, provider = fallback
        if "chat" not in (model.capabilities or []):
            return _openai_error(
                422,
                "The fallback model does not have the chat capability.",
                "capability_missing",
            )
    budget = await _budget_error(session, request.app.state.settings, call.user_id, model)
    if budget is not None:
        return budget
    settings: Settings = request.app.state.settings
    provider_body = dict(body)
    provider_body["model"] = model.model_name
    started = datetime.now(UTC)
    http = OutboundHTTP(timeout=settings.provider_timeout_seconds, retries=1)
    try:
        response = await http.request(
            "POST",
            f"{provider.base_url.rstrip('/')}/chat/completions",
            json=provider_body,
            headers=_provider_headers(provider, settings),
        )
    except CircuitOpenError:
        return _openai_error(
            503, "The provider circuit breaker is open.", "circuit_open", "server_error"
        )
    except Exception as exc:
        logger.warning("provider call failed", extra={"event": "provider_failure"})
        await _record_usage(
            session,
            call=call,
            model=model,
            provider=provider,
            tokens_in=0,
            tokens_out=0,
            status=502,
            latency_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
            failure=True,
        )
        return _openai_error(
            502,
            "The model provider is unavailable.",
            f"provider_error: {type(exc).__name__}",
            "server_error",
        )
    latency_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code >= 400 or not isinstance(payload, dict):
        await _record_usage(
            session,
            call=call,
            model=model,
            provider=provider,
            tokens_in=0,
            tokens_out=0,
            status=response.status_code if response.status_code >= 400 else 502,
            latency_ms=latency_ms,
            failure=True,
        )
        message = "The model provider rejected the request."
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict) and error.get("message"):
                message = str(error["message"])
        return _openai_error(
            response.status_code if response.status_code >= 400 else 502,
            message,
            "provider_rejected",
            "server_error" if response.status_code >= 500 else "invalid_request_error",
        )
    payload_dict: dict[str, Any] = payload if isinstance(payload, dict) else {}
    usage_raw = payload_dict.get("usage")
    usage: dict[str, Any] = usage_raw if isinstance(usage_raw, dict) else {}
    tokens_in = int(usage.get("prompt_tokens") or 0)
    tokens_out = int(usage.get("completion_tokens") or 0)
    await _record_usage(
        session,
        call=call,
        model=model,
        provider=provider,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        status=200,
        latency_ms=latency_ms,
    )
    return JSONResponse(status_code=200, content=payload)


@router.post("/embeddings")
async def embeddings(
    request: Request,
    call: InternalCall = Depends(internal_call),
    session: AsyncSession = Depends(get_session),
) -> JSONResponse:
    body = await request.json()
    alias = str(body.get("model") or "")
    try:
        model, provider = await _resolve_model(session, alias)
    except LookupError as exc:
        return _openai_error(404, str(exc), "model_not_found")
    if "embedding" not in (model.capabilities or []):
        return _openai_error(
            422, "The model does not have the embedding capability.", "capability_missing"
        )
    if not await _allowed_by_data_flow(session, model, call.data_classes):
        # A fallback would change the corpus embedding model; that needs a re-index.
        return _openai_error(
            403,
            "The data-flow policy forbids sending these data classes to this provider.",
            "data_flow_blocked",
            "permission_error",
        )
    locked = await _embedding_lock(session, model, call.purpose)
    if locked is not None:
        return locked
    budget = await _budget_error(session, request.app.state.settings, call.user_id, model)
    if budget is not None:
        return budget
    settings: Settings = request.app.state.settings
    provider_body = dict(body)
    provider_body["model"] = model.model_name
    started = datetime.now(UTC)
    http = OutboundHTTP(timeout=settings.provider_timeout_seconds, retries=1)
    try:
        response = await http.request(
            "POST",
            f"{provider.base_url.rstrip('/')}/embeddings",
            json=provider_body,
            headers=_provider_headers(provider, settings),
        )
    except Exception:
        await _record_usage(
            session,
            call=call,
            model=model,
            provider=provider,
            tokens_in=0,
            tokens_out=0,
            status=502,
            latency_ms=int((datetime.now(UTC) - started).total_seconds() * 1000),
            failure=True,
        )
        return _openai_error(
            502, "The embedding provider is unavailable.", "provider_error", "server_error"
        )
    latency_ms = int((datetime.now(UTC) - started).total_seconds() * 1000)
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if response.status_code >= 400 or not isinstance(payload, dict):
        await _record_usage(
            session,
            call=call,
            model=model,
            provider=provider,
            tokens_in=0,
            tokens_out=0,
            status=response.status_code,
            latency_ms=latency_ms,
            failure=True,
        )
        return _openai_error(
            response.status_code if response.status_code >= 400 else 502,
            "The embedding provider rejected the request.",
            "provider_rejected",
            "server_error" if response.status_code >= 500 else "invalid_request_error",
        )
    payload_dict: dict[str, Any] = payload if isinstance(payload, dict) else {}
    usage_raw = payload_dict.get("usage")
    usage: dict[str, Any] = usage_raw if isinstance(usage_raw, dict) else {}
    tokens_in = int(usage.get("prompt_tokens") or 0)
    await _record_usage(
        session,
        call=call,
        model=model,
        provider=provider,
        tokens_in=tokens_in,
        tokens_out=0,
        status=200,
        latency_ms=latency_ms,
    )
    return JSONResponse(status_code=200, content=payload)
