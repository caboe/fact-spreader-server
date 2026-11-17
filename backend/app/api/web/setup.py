"""First-run setup wizard routes (IMPLEMENT Phase 5).

The wizard is a browser-session API under ``/api``, not part of the public ``/v1``
protocol. Before an admin exists it is protected by the deployment's setup token; after
that it requires ``config:manage`` and an incomplete setup. Nothing that spends a model
call runs before completion (see ``setup_gate``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    SetupAdminCreated,
    SetupAdminRequest,
    SetupCompleted,
    SetupModelsAssigned,
    SetupModelsRequest,
    SetupModerationTest,
    SetupOrganizationRequest,
    SetupProviderRequest,
    SetupProviderTested,
    SetupStatus,
    SetupTotpConfirmed,
    SetupTotpRequest,
)
from app.core.errors import AppError
from app.core.ids import utcnow
from app.db.session import get_session
from app.services import setup as wizard
from app.services.auth import Principal, require_permission

router = APIRouter(prefix="/api/setup", tags=["setup"])
ConfigManage = Annotated[Principal, Depends(require_permission("config:manage"))]


async def _not_complete(session: AsyncSession) -> None:
    instance = await wizard.get_instance(session)
    if instance is not None and instance.setup_complete:
        raise AppError(409, "setup_complete", "Setup is already complete.")


@router.get("/status", response_model=SetupStatus)
async def status(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SetupStatus:
    return SetupStatus.model_validate(await wizard.setup_state(session, request.app.state.settings))


@router.post("/admin", status_code=201, response_model=SetupAdminCreated)
async def create_admin(
    body: SetupAdminRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SetupAdminCreated:
    user, secret = await wizard.create_admin(
        session,
        request.app.state.settings,
        token=body.token,
        email=body.email,
        password=body.password,
        display_name=body.display_name,
    )
    return SetupAdminCreated(
        user_id=user.id,
        email=user.email,
        totp_secret=secret,
        provisioning_uri=wizard.provisioning_uri(secret, user.email),
    )


@router.post("/admin/totp", response_model=SetupTotpConfirmed)
async def confirm_admin_totp(
    body: SetupTotpRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SetupTotpConfirmed:
    codes = await wizard.confirm_admin_totp(
        session, request.app.state.settings, token=body.token, code=body.code
    )
    return SetupTotpConfirmed(recovery_codes=codes)


@router.post("/organization", response_model=SetupStatus)
async def organization(
    body: SetupOrganizationRequest,
    request: Request,
    principal: ConfigManage,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SetupStatus:
    await _not_complete(session)
    await wizard.set_organization(
        session,
        name=body.name,
        organization=body.organization,
        contact=body.contact,
        overview_public=body.overview_public,
        monthly_budget_usd=body.monthly_budget_usd,
    )
    return SetupStatus.model_validate(await wizard.setup_state(session, request.app.state.settings))


@router.post("/provider", response_model=SetupProviderTested)
async def provider(
    body: SetupProviderRequest,
    request: Request,
    principal: ConfigManage,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SetupProviderTested:
    await _not_complete(session)
    row, models = await wizard.configure_provider(
        session,
        request.app.state.settings,
        name=body.name,
        base_url=body.base_url,
        api_key=body.api_key,
        is_local=body.is_local,
        use=body.use,
    )
    return SetupProviderTested(provider_id=row.id, models=models, tested_at=utcnow())


@router.post("/models", response_model=SetupModelsAssigned)
async def models(
    body: SetupModelsRequest,
    request: Request,
    principal: ConfigManage,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SetupModelsAssigned:
    await _not_complete(session)
    rows = await wizard.assign_models(
        session,
        request.app.state.settings,
        chat_model=body.chat_model,
        embedding_model=body.embedding_model,
        embedding_dim=body.embedding_dim,
        multilingual=body.multilingual,
    )
    return SetupModelsAssigned(
        aliases=[row.gateway_alias for row in rows],
        chat_model=body.chat_model,
        embedding_model=body.embedding_model,
    )


@router.post("/moderation-test", response_model=SetupModerationTest)
async def moderation_test(
    request: Request,
    principal: ConfigManage,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SetupModerationTest:
    await _not_complete(session)
    result = await wizard.run_moderation_test(session, request.app.state.settings)
    return SetupModerationTest(
        backend=result.backend, flagged=result.flagged, categories=list(result.categories)
    )


@router.post("/complete", response_model=SetupCompleted)
async def complete(
    request: Request,
    principal: ConfigManage,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SetupCompleted:
    instance = await wizard.complete_setup(session, request.app.state.settings)
    return SetupCompleted(complete=True, instance_id=instance.id)
