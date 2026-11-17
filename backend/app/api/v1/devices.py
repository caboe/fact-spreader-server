"""Device tokens for the browser extension (PROTOCOL §11).

A token is shown once, stored hashed, defaults to `claims:submit`, and can never carry a
permission its owner does not have. The endpoint keeps the token management in the shared
API so the web UI and an authenticated client use the same contract.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import DeviceCreate, DeviceCreated, DeviceInfo
from app.core.errors import AppError, permission_denied
from app.core.ids import new_id, utcnow
from app.core.security import new_device_token
from app.db.models import DeviceToken
from app.db.session import get_session
from app.services.auth import Principal, current_principal

router = APIRouter(prefix="/v1/devices", tags=["devices"])
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


def _info(row: DeviceToken) -> DeviceInfo:
    return DeviceInfo(
        id=row.id,
        name=row.name,
        permissions=list(row.permissions or []),
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        revoked_at=row.revoked_at,
    )


@router.post("", status_code=201, response_model=DeviceCreated)
async def create_device(
    body: DeviceCreate,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DeviceCreated:
    requested = body.permissions or ["claims:submit"]
    if "devices:manage" in requested and "devices:manage" not in principal.permissions:
        raise permission_denied("A device token cannot exceed its owner.")
    if not set(requested) <= set(principal.permissions):
        raise AppError(422, "permission_escalation", "A device token cannot exceed its owner.")
    plaintext, prefix, digest = new_device_token()
    row = DeviceToken(
        id=new_id("dev"),
        user_id=principal.user_id,
        name=body.name,
        token_hash=digest,
        token_prefix=prefix,
        permissions=sorted(set(requested)),
        created_at=utcnow(),
    )
    session.add(row)
    await session.commit()
    return DeviceCreated(device=_info(row), token=plaintext)


@router.get("", response_model=list[DeviceInfo])
async def list_devices(
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DeviceInfo]:
    statement = select(DeviceToken).where(DeviceToken.user_id == principal.user_id)
    if principal.has("devices:manage"):
        statement = select(DeviceToken)
    rows = (await session.execute(statement.order_by(DeviceToken.created_at.desc()))).scalars()
    return [_info(row) for row in rows]


@router.delete("/{device_id}", status_code=204)
async def revoke_device(
    device_id: str,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    row = await session.get(DeviceToken, device_id)
    if row is None:
        raise AppError(404, "not_found", "The device does not exist.")
    if row.user_id != principal.user_id and not principal.has("devices:manage"):
        raise AppError(404, "not_found", "The device does not exist.")
    row.revoked_at = utcnow()
    await session.commit()
