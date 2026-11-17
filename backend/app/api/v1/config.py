"""Operator configuration: providers, models, capability tests, roles and data flow.

Everything here requires ``config:manage``; provider keys are write-only. The role
assignment endpoint and the model list use the same rule from ``services.capabilities``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    CapabilityProbeReport,
    CapabilityProbeRequest,
    DataFlowPolicy,
    ModelCreate,
    ModelInfo,
    ModelUpdate,
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
    RoleAssignment,
    RoleInfo,
)
from app.db.session import get_session
from app.services import publisher_overrides, registry
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
