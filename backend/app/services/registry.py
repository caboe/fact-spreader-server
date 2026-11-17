"""Provider and model registry with capability evidence (IMPLEMENT Phase 6).

Provider keys are write-only through this API: they are encrypted before the row is
written and never returned. A model's capabilities are declared on add and become
``tested`` only through a probe; role assignment rejects an untested mandatory capability
with the same rule the model list filters by.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    CapabilityProbeReport,
    CapabilityTestInfo,
    DataFlowPolicy,
    ModelCreate,
    ModelInfo,
    ModelUpdate,
    ProviderCreate,
    ProviderInfo,
    ProviderTestResult,
    ProviderUpdate,
    RoleInfo,
)
from app.core.config import Settings
from app.core.errors import AppError
from app.core.ids import new_id, utcnow
from app.db.models import (
    Instance,
    ModelCapabilityTest,
    ModelRecord,
    Provider,
    Setting,
    UsageEvent,
)
from app.llm.aliases import ALL_ALIASES
from app.services import capability_probes
from app.services.capabilities import (
    CAPABILITIES,
    ROLE_LABELS,
    ROLE_REQUIREMENTS,
    ModelView,
    assignment_reasons,
)
from app.services.providers import probe_provider, upsert_provider


def _provider_info(provider: Provider) -> ProviderInfo:
    return ProviderInfo(
        id=provider.id,
        name=provider.name,
        base_url=provider.base_url,
        is_local=provider.is_local,
        enabled=provider.enabled,
        has_key=provider.api_key_enc is not None,
        created_at=provider.created_at,
    )


async def _tests_by_model(
    session: AsyncSession, model_ids: list[str]
) -> dict[str, dict[str, ModelCapabilityTest]]:
    if not model_ids:
        return {}
    rows = (
        await session.execute(
            select(ModelCapabilityTest).where(ModelCapabilityTest.model_id.in_(model_ids))
        )
    ).scalars()
    grouped: dict[str, dict[str, ModelCapabilityTest]] = {}
    for row in rows:
        grouped.setdefault(row.model_id, {})[row.capability] = row
    return grouped


def _model_view(
    model: ModelRecord,
    tests: dict[str, ModelCapabilityTest],
    source_tests: dict[str, ModelCapabilityTest] | None = None,
) -> ModelView:
    combined: dict[str, ModelCapabilityTest] = dict(source_tests or {})
    combined.update(tests)
    return ModelView(
        capabilities=frozenset(model.capabilities or []),
        tested=frozenset(
            capability for capability, row in combined.items() if row.status == "tested"
        ),
        context_window=model.context_window,
        embedding_dim=model.embedding_dim,
        multilingual=model.multilingual,
    )


def _test_info(row: ModelCapabilityTest) -> CapabilityTestInfo:
    return CapabilityTestInfo(
        capability=row.capability,
        status=row.status,
        detail=row.detail or "",
        dimension=row.dimension,
        latency_ms=row.latency_ms,
        tested_at=row.tested_at,
    )


def _model_info(model: ModelRecord, tests: dict[str, ModelCapabilityTest]) -> ModelInfo:
    return ModelInfo(
        id=model.id,
        provider_id=model.provider_id,
        model_name=model.model_name,
        gateway_alias=model.gateway_alias,
        source_model_id=model.source_model_id,
        capabilities=list(model.capabilities or []),
        tested_capabilities=sorted(
            capability for capability, row in tests.items() if row.status == "tested"
        ),
        context_window=model.context_window,
        embedding_dim=model.embedding_dim,
        multilingual=model.multilingual,
        is_local=model.is_local,
        enabled=model.enabled,
        input_cost_per_mtok=float(model.input_cost_per_mtok),
        output_cost_per_mtok=float(model.output_cost_per_mtok),
        created_at=model.created_at,
    )


async def list_providers(session: AsyncSession) -> list[ProviderInfo]:
    rows = (await session.execute(select(Provider).order_by(Provider.created_at))).scalars()
    return [_provider_info(row) for row in rows]


async def create_provider(
    session: AsyncSession, settings: Settings, body: ProviderCreate
) -> tuple[ProviderInfo, list[str]]:
    models: list[str] = []
    if body.test_connection:
        models = await probe_provider(body.base_url, body.api_key)
    provider = await upsert_provider(
        session,
        settings,
        name=body.name,
        base_url=body.base_url,
        api_key=body.api_key,
        is_local=body.is_local,
    )
    await session.commit()
    return _provider_info(provider), models


async def update_provider(
    session: AsyncSession, settings: Settings, provider_id: str, body: ProviderUpdate
) -> ProviderInfo:
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise AppError(404, "not_found", "The provider does not exist.")
    if body.name is not None:
        provider.name = body.name
    if body.base_url is not None:
        provider.base_url = body.base_url.rstrip("/")
    if body.api_key is not None:
        from app.services.providers import box

        provider.api_key_enc = box(settings).encrypt(body.api_key)
    if body.is_local is not None:
        provider.is_local = body.is_local
    if body.enabled is not None:
        provider.enabled = body.enabled
    await session.commit()
    return _provider_info(provider)


async def test_provider(
    session: AsyncSession, settings: Settings, provider_id: str
) -> ProviderTestResult:
    provider = await session.get(Provider, provider_id)
    if provider is None:
        raise AppError(404, "not_found", "The provider does not exist.")
    from app.services.providers import box

    api_key = (
        box(settings).decrypt(provider.api_key_enc) if provider.api_key_enc is not None else None
    )
    started = utcnow()
    models = await probe_provider(provider.base_url, api_key)
    latency_ms = int((utcnow() - started).total_seconds() * 1000)
    return ProviderTestResult(
        provider_id=provider.id, reachable=True, models=models, latency_ms=latency_ms
    )


async def list_models(session: AsyncSession) -> list[ModelInfo]:
    models = (
        (await session.execute(select(ModelRecord).order_by(ModelRecord.created_at)))
        .scalars()
        .all()
    )
    grouped = await _tests_by_model(session, [model.id for model in models])
    return [_model_info(model, grouped.get(model.id, {})) for model in models]


def _validate_capabilities(capabilities: list[str]) -> list[str]:
    unknown = sorted(set(capabilities) - set(CAPABILITIES))
    if unknown:
        raise AppError(422, "unknown_capability", f"Unknown capabilities: {', '.join(unknown)}")
    return sorted(set(capabilities))


async def create_model(session: AsyncSession, body: ModelCreate) -> ModelInfo:
    provider = await session.get(Provider, body.provider_id)
    if provider is None:
        raise AppError(404, "provider_not_found", "The provider does not exist.")
    capabilities = _validate_capabilities(body.capabilities)
    model = ModelRecord(
        id=new_id("mdl"),
        provider_id=provider.id,
        gateway_alias=None,
        source_model_id=None,
        model_name=body.model_name,
        capabilities=capabilities,
        context_window=body.context_window,
        embedding_dim=body.embedding_dim,
        multilingual=body.multilingual,
        is_local=provider.is_local,
        enabled=True,
        input_cost_per_mtok=Decimal(str(body.input_cost_per_mtok)),
        output_cost_per_mtok=Decimal(str(body.output_cost_per_mtok)),
        created_at=utcnow(),
    )
    session.add(model)
    await session.commit()
    return _model_info(model, {})


async def update_model(session: AsyncSession, model_id: str, body: ModelUpdate) -> ModelInfo:
    model = await session.get(ModelRecord, model_id)
    if model is None:
        raise AppError(404, "not_found", "The model does not exist.")
    if body.capabilities is not None:
        model.capabilities = _validate_capabilities(body.capabilities)
    for field in ("context_window", "embedding_dim", "multilingual", "enabled"):
        value = getattr(body, field)
        if value is not None:
            setattr(model, field, value)
    if body.input_cost_per_mtok is not None:
        model.input_cost_per_mtok = Decimal(str(body.input_cost_per_mtok))
    if body.output_cost_per_mtok is not None:
        model.output_cost_per_mtok = Decimal(str(body.output_cost_per_mtok))
    await session.commit()
    grouped = await _tests_by_model(session, [model.id])
    return _model_info(model, grouped.get(model.id, {}))


async def probe_model(
    session: AsyncSession,
    settings: Settings,
    model_id: str,
    capabilities: list[str],
) -> CapabilityProbeReport:
    model = await session.get(ModelRecord, model_id)
    if model is None:
        raise AppError(404, "not_found", "The model does not exist.")
    if model.gateway_alias is not None and model.source_model_id is None:
        raise AppError(
            409,
            "probe_requires_base_model",
            "Probe the base model in the registry, not a role binding.",
        )
    provider = await session.get(Provider, model.provider_id)
    if provider is None:
        raise AppError(404, "provider_not_found", "The provider does not exist.")
    requested = capabilities or list(model.capabilities or [])
    if not requested:
        raise AppError(422, "no_capabilities", "Declare at least one capability first.")
    unknown = sorted(set(requested) - set(CAPABILITIES))
    if unknown:
        raise AppError(422, "unknown_capability", f"Unknown capabilities: {', '.join(unknown)}")
    instance = (await session.execute(select(Instance).limit(1))).scalar_one_or_none()
    month_start = datetime(utcnow().year, utcnow().month, 1, tzinfo=UTC)
    if instance is not None:
        spent = (
            await session.execute(
                select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(
                    UsageEvent.created_at >= month_start
                )
            )
        ).scalar_one()
        if Decimal(spent) >= instance.monthly_budget_usd:
            raise AppError(
                429,
                "budget_exceeded",
                "The monthly LLM budget is exhausted; capability probes are paused.",
            )
    results: list[CapabilityTestInfo] = []
    for capability in requested:
        result = await capability_probes.probe_capability(capability, provider, model, settings)
        row = (
            await session.execute(
                select(ModelCapabilityTest).where(
                    ModelCapabilityTest.model_id == model.id,
                    ModelCapabilityTest.capability == capability,
                )
            )
        ).scalar_one_or_none()
        now = utcnow()
        if row is None:
            row = ModelCapabilityTest(
                id=new_id("cap"),
                model_id=model.id,
                capability=capability,
                status=result.status,
                detail=result.detail[:500],
                dimension=result.dimension,
                latency_ms=result.latency_ms,
                tested_at=now,
            )
            session.add(row)
        else:
            row.status = result.status
            row.detail = result.detail[:500]
            row.dimension = result.dimension
            row.latency_ms = result.latency_ms
            row.tested_at = now
        cost = (
            Decimal(result.tokens_in) * model.input_cost_per_mtok
            + Decimal(result.tokens_out) * model.output_cost_per_mtok
        ) / Decimal(1_000_000)
        session.add(
            UsageEvent(
                id=new_id("use"),
                request_id=None,
                user_id=None,
                api_key_id=None,
                consumer="probe",
                role=f"probe:{capability}",
                provider=provider.name,
                model=model.model_name,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                cost_usd=cost.quantize(Decimal("0.000001")),
                cost_estimated=True,
                latency_ms=result.latency_ms,
                status=200 if result.status in {"tested", "assumed"} else 502,
                data_classes=[],
                created_at=now,
            )
        )
        results.append(
            CapabilityTestInfo(
                capability=result.capability,
                status=result.status,
                detail=result.detail,
                dimension=result.dimension,
                latency_ms=result.latency_ms,
                tested_at=now,
            )
        )
    await session.commit()
    return CapabilityProbeReport(model_id=model.id, results=results)


async def role_infos(session: AsyncSession) -> list[RoleInfo]:
    bindings = (
        (
            await session.execute(
                select(ModelRecord).where(ModelRecord.gateway_alias.in_(list(ALL_ALIASES)))
            )
        )
        .scalars()
        .all()
    )
    by_alias = {row.gateway_alias: row for row in bindings}
    source_ids = [row.source_model_id for row in bindings if row.source_model_id]
    source_tests = await _tests_by_model(session, source_ids)
    binding_tests = await _tests_by_model(session, [row.id for row in bindings])
    infos: list[RoleInfo] = []
    for alias, requirement in ROLE_REQUIREMENTS.items():
        binding = by_alias.get(alias)
        info = RoleInfo(
            alias=alias,
            label=ROLE_LABELS[alias],
            required_capabilities=list(requirement.capabilities),
            min_context=requirement.min_context,
            multilingual=requirement.multilingual,
            embedding_dim=requirement.embedding_dim,
        )
        if binding is None:
            info.reasons = ["not_assigned"]
        if binding is not None:
            tests = binding_tests.get(binding.id, {})
            view = _model_view(binding, tests, source_tests.get(binding.source_model_id or "", {}))
            info.model = _model_info(binding, tests)
            info.reasons = assignment_reasons(alias, view)
            info.suitable = not info.reasons
        infos.append(info)
    return infos


async def assign_role(session: AsyncSession, alias: str, model_id: str) -> RoleInfo:
    if alias not in ROLE_REQUIREMENTS:
        raise AppError(404, "unknown_role", f"Unknown gateway role {alias!r}.")
    model = await session.get(ModelRecord, model_id)
    if model is None:
        raise AppError(404, "not_found", "The model does not exist.")
    tests = (await _tests_by_model(session, [model.id])).get(model.id, {})
    source_tests: dict[str, ModelCapabilityTest] = {}
    if model.source_model_id:
        source_tests = (await _tests_by_model(session, [model.source_model_id])).get(
            model.source_model_id, {}
        )
    view = _model_view(model, tests, source_tests)
    reasons = assignment_reasons(alias, view)
    if reasons:
        raise AppError(
            422,
            "assignment_rejected",
            "The model does not satisfy this role: " + ", ".join(reasons),
            extra={"reasons": reasons},
        )
    binding = (
        await session.execute(select(ModelRecord).where(ModelRecord.gateway_alias == alias))
    ).scalar_one_or_none()
    now = utcnow()
    if binding is None:
        binding = ModelRecord(
            id=new_id("mdl"),
            provider_id=model.provider_id,
            gateway_alias=alias,
            source_model_id=model.id,
            model_name=model.model_name,
            capabilities=list(model.capabilities or []),
            context_window=model.context_window,
            embedding_dim=model.embedding_dim,
            multilingual=model.multilingual,
            is_local=model.is_local,
            enabled=True,
            input_cost_per_mtok=model.input_cost_per_mtok,
            output_cost_per_mtok=model.output_cost_per_mtok,
            created_at=now,
        )
        session.add(binding)
    else:
        binding.provider_id = model.provider_id
        binding.source_model_id = model.id
        binding.model_name = model.model_name
        binding.capabilities = list(model.capabilities or [])
        binding.context_window = model.context_window
        binding.embedding_dim = model.embedding_dim
        binding.multilingual = model.multilingual
        binding.is_local = model.is_local
        binding.enabled = True
        binding.input_cost_per_mtok = model.input_cost_per_mtok
        binding.output_cost_per_mtok = model.output_cost_per_mtok
    await session.commit()
    infos = await role_infos(session)
    return next(info for info in infos if info.alias == alias)


async def get_data_flow(session: AsyncSession) -> DataFlowPolicy:
    row = await session.get(Setting, "data_flow.allow_external")
    value: dict[str, Any] = {}
    if row is not None and isinstance(row.value, dict):
        value = dict(row.value)
    fallback = value.get("fallback_alias")
    return DataFlowPolicy(
        allow_external=bool(value.get("allow", True)),
        fallback_alias=str(fallback) if fallback else None,
    )


async def set_data_flow(session: AsyncSession, policy: DataFlowPolicy) -> DataFlowPolicy:
    if policy.fallback_alias is not None and policy.fallback_alias not in ALL_ALIASES:
        raise AppError(422, "unknown_alias", "The fallback alias is not a gateway role.")
    row = await session.get(Setting, "data_flow.allow_external")
    value = {"allow": policy.allow_external, "fallback_alias": policy.fallback_alias}
    if row is None:
        session.add(Setting(key="data_flow.allow_external", value=value, updated_at=utcnow()))
    else:
        row.value = value
        row.updated_at = utcnow()
    await session.commit()
    return policy


async def get_role_budgets(session: AsyncSession) -> dict[str, float]:
    row = await session.get(Setting, "budgets.roles")
    value: dict[str, Any] = {}
    if row is not None and isinstance(row.value, dict):
        value = row.value
    raw = value.get("roles")
    roles = raw if isinstance(raw, dict) else {}
    return {str(alias): float(limit) for alias, limit in dict(roles).items() if limit is not None}


async def set_role_budgets(session: AsyncSession, roles: dict[str, float]) -> dict[str, float]:
    clean: dict[str, float] = {}
    for alias, limit in roles.items():
        if alias not in ALL_ALIASES:
            raise AppError(422, "unknown_alias", f"Unknown gateway role {alias!r}.")
        amount = float(limit)
        if amount < 0:
            raise AppError(422, "invalid_budget", "A role budget cannot be negative.")
        clean[alias] = amount
    row = await session.get(Setting, "budgets.roles")
    value = {"roles": clean}
    if row is None:
        session.add(Setting(key="budgets.roles", value=value, updated_at=utcnow()))
    else:
        row.value = value
        row.updated_at = utcnow()
    await session.commit()
    return clean
