"""Operator configuration: providers, models, capability tests, roles and data flow.

Everything here requires ``config:manage``; provider keys are write-only. The role
assignment endpoint and the model list use the same rule from ``services.capabilities``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    CapabilityProbeReport,
    CapabilityProbeRequest,
    ChecklistOverrideRequest,
    DataFlowPolicy,
    MethodologySummary,
    ModelCreate,
    ModelInfo,
    ModelUpdate,
    PatternOverrideRequest,
    PersonaInfo,
    PersonaWrite,
    ProviderCreate,
    ProviderCreated,
    ProviderInfo,
    ProviderTestResult,
    ProviderUpdate,
    PublisherDiffEntry,
    PublisherEntryInfo,
    PublisherImpactEntry,
    PublisherListInfo,
    PublisherOverridesRequest,
    PublisherResolveRequest,
    PublisherResolveResponse,
    ReindexAccepted,
    ReindexRequest,
    ReindexStatus,
    RoleAssignment,
    RoleBudgets,
    RoleInfo,
)
from app.core.errors import AppError
from app.db.models import Job as JobRow
from app.db.session import get_session
from app.services import (
    methodology_overrides,
    persona_overrides,
    publisher_overrides,
    registry,
    reindex,
)
from app.services.auth import Principal, require_permission

router = APIRouter(prefix="/v1/config", tags=["config"])
ConfigManage = Annotated[Principal, Depends(require_permission("config:manage"))]
SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/providers", response_model=list[ProviderInfo])
async def list_providers(principal: ConfigManage, session: SessionDep) -> list[ProviderInfo]:
    return await registry.list_providers(session)


@router.post("/providers", status_code=201, response_model=ProviderCreated)
async def create_provider(
    body: ProviderCreate,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> ProviderCreated:
    info, models = await registry.create_provider(session, request.app.state.settings, body)
    return ProviderCreated(provider=info, models=models)


@router.patch("/providers/{provider_id}", response_model=ProviderInfo)
async def update_provider(
    provider_id: str,
    body: ProviderUpdate,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> ProviderInfo:
    return await registry.update_provider(session, request.app.state.settings, provider_id, body)


@router.post("/providers/{provider_id}/test", response_model=ProviderTestResult)
async def test_provider(
    provider_id: str,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> ProviderTestResult:
    return await registry.test_provider(session, request.app.state.settings, provider_id)


@router.get("/models", response_model=list[ModelInfo])
async def list_models(principal: ConfigManage, session: SessionDep) -> list[ModelInfo]:
    return await registry.list_models(session)


@router.post("/models", status_code=201, response_model=ModelInfo)
async def create_model(
    body: ModelCreate,
    principal: ConfigManage,
    session: SessionDep,
) -> ModelInfo:
    return await registry.create_model(session, body)


@router.patch("/models/{model_id}", response_model=ModelInfo)
async def update_model(
    model_id: str,
    body: ModelUpdate,
    principal: ConfigManage,
    session: SessionDep,
) -> ModelInfo:
    return await registry.update_model(session, model_id, body)


@router.post("/models/{model_id}/probe", response_model=CapabilityProbeReport)
async def probe_model(
    model_id: str,
    body: CapabilityProbeRequest,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> CapabilityProbeReport:
    return await registry.probe_model(
        session, request.app.state.settings, model_id, body.capabilities
    )


@router.get("/roles", response_model=list[RoleInfo])
async def list_roles(principal: ConfigManage, session: SessionDep) -> list[RoleInfo]:
    return await registry.role_infos(session)


@router.put("/roles/{alias}", response_model=RoleInfo)
async def assign_role(
    alias: str,
    body: RoleAssignment,
    principal: ConfigManage,
    session: SessionDep,
) -> RoleInfo:
    return await registry.assign_role(session, alias, body.model_id)


@router.get("/data-flow", response_model=DataFlowPolicy)
async def get_data_flow(principal: ConfigManage, session: SessionDep) -> DataFlowPolicy:
    return await registry.get_data_flow(session)


@router.put("/data-flow", response_model=DataFlowPolicy)
async def set_data_flow(
    body: DataFlowPolicy,
    principal: ConfigManage,
    session: SessionDep,
) -> DataFlowPolicy:
    return await registry.set_data_flow(session, body)


@router.get("/publishers", response_model=PublisherListInfo)
async def list_publishers(
    request: Request, principal: ConfigManage, session: SessionDep
) -> PublisherListInfo:
    base = request.app.state.publisher_base
    overrides = await publisher_overrides.load_overrides(session)
    effective = publisher_overrides.effective_registry(base, overrides)
    by_key = {str(entry["key"]): entry for entry in overrides if entry.get("key")}
    entries = [
        PublisherEntryInfo(
            key=str(entry.get("key") or ""),
            publisher=entry.get("publisher"),
            grade=str(entry.get("grade", "D")),
            disputed=bool(entry.get("disputed")),
            overridden=str(entry.get("key")) in by_key,
        )
        for entry in effective.entries
        if entry.get("key")
    ]
    return PublisherListInfo(
        version=base.version,
        effective_version=effective.version,
        entries=entries,
        overrides=overrides,
    )


@router.put("/publishers/overrides", response_model=PublisherListInfo)
async def set_publisher_overrides(
    body: PublisherOverridesRequest,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> PublisherListInfo:
    base = request.app.state.publisher_base
    cleaned = await publisher_overrides.write_overrides(
        session, base, [entry.model_dump(exclude_none=True) for entry in body.entries]
    )
    request.app.state.publishers = publisher_overrides.effective_registry(base, cleaned)
    return await list_publishers(request, principal, session)


@router.get("/publishers/diff", response_model=list[PublisherDiffEntry])
async def publisher_diff(
    request: Request, principal: ConfigManage, session: SessionDep
) -> list[PublisherDiffEntry]:
    base = request.app.state.publisher_base
    changes = publisher_overrides.diff(base, await publisher_overrides.load_overrides(session))
    return [PublisherDiffEntry(**change) for change in changes]


@router.post("/publishers/resolve", response_model=PublisherResolveResponse)
async def resolve_publisher(
    body: PublisherResolveRequest,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> PublisherResolveResponse:
    base = request.app.state.publisher_base
    effective = publisher_overrides.effective_registry(
        base, await publisher_overrides.load_overrides(session)
    )
    match = effective.resolve(publisher=body.publisher, url=body.url, doi=body.doi)
    return PublisherResolveResponse(
        grade=match.grade, basis=match.basis, effective_version=effective.version
    )


@router.get("/publishers/impact", response_model=list[PublisherImpactEntry])
async def publisher_impact(
    request: Request, principal: ConfigManage, session: SessionDep
) -> list[PublisherImpactEntry]:
    base = request.app.state.publisher_base
    overrides = await publisher_overrides.load_overrides(session)
    affected = await publisher_overrides.affected_cache_entries(session, base, overrides)
    return [PublisherImpactEntry(**entry) for entry in affected]


def _persona_info(persona: Any, base: Any, overrides: dict[str, Any]) -> PersonaInfo:
    stored = overrides.get(persona.id) or {}
    return PersonaInfo(
        id=persona.id,
        name=persona.name,
        version=persona.version,
        enabled=persona.enabled,
        custom=base.get(persona.id) is None,
        overridden=persona.id in overrides,
        address_mode=persona.address_mode,
        tone=persona.tone,
        didactics=persona.didactics,
        moral_framing=persona.moral_framing,
        verdict_in_text=persona.verdict_in_text,
        substance_display=persona.substance_display,
        max_words=persona.max_words,
        rules=list(persona.rules),
        forbidden=list(persona.forbidden),
        checks=list(persona.checks),
        test_issues=[str(item) for item in stored.get("test_issues") or []],
    )


@router.get("/personas", response_model=list[PersonaInfo])
async def list_personas(
    request: Request, principal: ConfigManage, session: SessionDep
) -> list[PersonaInfo]:
    base = request.app.state.persona_base
    overrides = await persona_overrides.load_overrides(session)
    effective = persona_overrides.effective_registry(base, overrides)
    return [_persona_info(persona, base, overrides) for persona in effective.personas.values()]


@router.put("/personas/{persona_id}", response_model=PersonaInfo)
async def write_persona(
    persona_id: str,
    body: PersonaWrite,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> PersonaInfo:
    base = request.app.state.persona_base
    fields = body.model_dump(exclude_none=True, exclude={"override_test"})
    await persona_overrides.write_persona(
        session,
        base,
        persona_id,
        fields,
        override_test=body.override_test,
        actor_id=principal.user_id,
    )
    overrides = await persona_overrides.load_overrides(session)
    request.app.state.personas = persona_overrides.effective_registry(base, overrides)
    return _persona_info(
        persona_overrides.build_persona(base, persona_id, overrides), base, overrides
    )


@router.delete("/personas/{persona_id}", status_code=204)
async def delete_persona(
    persona_id: str,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> None:
    base = request.app.state.persona_base
    await persona_overrides.delete_persona(session, base, persona_id)
    overrides = await persona_overrides.load_overrides(session)
    request.app.state.personas = persona_overrides.effective_registry(base, overrides)


@router.get("/methodology", response_model=MethodologySummary)
async def get_methodology(
    request: Request, principal: ConfigManage, session: SessionDep
) -> MethodologySummary:
    base = request.app.state.methodology_base
    overrides = await methodology_overrides.load_overrides(session)
    effective = methodology_overrides.effective_methodology(base, overrides)
    return MethodologySummary(
        patterns_version=effective.patterns_version,
        version=int(overrides.get("version", 0)),
        checklists=[
            {
                "topic": checklist.topic,
                "name": checklist.name,
                "version": checklist.version,
                "staleness_days": checklist.staleness_days,
                "confounders": [
                    {
                        "id": confounder.id,
                        "label": confounder.label,
                        "retrieval_hint": confounder.retrieval_hint,
                    }
                    for confounder in checklist.confounders
                ],
            }
            for checklist in effective.checklists.values()
        ],
        patterns=[{"id": pattern_id, **value} for pattern_id, value in effective.patterns.items()],
        overrides=overrides,
    )


@router.put("/methodology/patterns/{pattern_id}", response_model=MethodologySummary)
async def write_methodology_pattern(
    pattern_id: str,
    body: PatternOverrideRequest,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> MethodologySummary:
    base = request.app.state.methodology_base
    await methodology_overrides.write_pattern(
        session,
        base,
        pattern_id,
        body.model_dump(exclude_none=True),
        actor_id=principal.user_id,
    )
    request.app.state.methodology = await methodology_overrides.effective_methodology_for(
        session,
        request.app.state.settings.checklist_dir,
        request.app.state.settings.pattern_list_path,
    )
    return await get_methodology(request, principal, session)


@router.put("/methodology/checklists/{topic}", response_model=MethodologySummary)
async def write_methodology_checklist(
    topic: str,
    body: ChecklistOverrideRequest,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> MethodologySummary:
    base = request.app.state.methodology_base
    fields: dict[str, Any] = {}
    if body.staleness_days is not None:
        fields["staleness_days"] = body.staleness_days
    if body.confounders is not None:
        fields["confounders"] = [item.model_dump(exclude_none=True) for item in body.confounders]
    await methodology_overrides.write_checklist(
        session, base, topic, fields, actor_id=principal.user_id
    )
    request.app.state.methodology = await methodology_overrides.effective_methodology_for(
        session,
        request.app.state.settings.checklist_dir,
        request.app.state.settings.pattern_list_path,
    )
    return await get_methodology(request, principal, session)


@router.post("/reindex", status_code=202, response_model=ReindexAccepted)
async def start_reindex(
    body: ReindexRequest,
    request: Request,
    principal: ConfigManage,
    session: SessionDep,
) -> ReindexAccepted:
    job, documents, model_id, changed = await reindex.create_reindex_job(
        session,
        request.app.state.settings,
        user_id=principal.user_id,
        reason=body.reason,
        confirm=body.confirm,
    )
    return ReindexAccepted(
        job_id=job.id, documents=documents, embedding_model_id=model_id, model_changed=changed
    )


@router.get("/reindex/{job_id}", response_model=ReindexStatus)
async def reindex_status(
    job_id: str, principal: ConfigManage, session: SessionDep
) -> ReindexStatus:
    job = await session.get(JobRow, job_id)
    if job is None or job.kind != "reindex":
        raise AppError(404, "not_found", "The re-index job does not exist.")
    return ReindexStatus(
        job_id=job.id,
        state=job.state,
        progress=job.progress,
        documents=len((job.payload or {}).get("document_ids") or []),
        error=job.error,
    )


@router.get("/budgets", response_model=RoleBudgets)
async def get_budgets(principal: ConfigManage, session: SessionDep) -> RoleBudgets:
    return RoleBudgets(roles=await registry.get_role_budgets(session))


@router.put("/budgets", response_model=RoleBudgets)
async def set_budgets(
    body: RoleBudgets, principal: ConfigManage, session: SessionDep
) -> RoleBudgets:
    return RoleBudgets(roles=await registry.set_role_budgets(session, body.roles))
