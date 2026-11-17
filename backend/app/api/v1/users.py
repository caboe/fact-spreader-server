"""User administration: roles, explicit grants and per-user limits (PROTOCOL §2)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    UserCreateRequest,
    UserInfo,
    UserPasswordResetRequest,
    UserUpdateRequest,
)
from app.contracts.enums import PERMISSIONS, ROLE_TEMPLATES
from app.core.errors import AppError
from app.core.ids import new_id, utcnow
from app.core.security import hash_password, validate_password
from app.db.models import AuditLog, SessionToken, User
from app.db.session import get_session
from app.services.auth import Principal, effective_permissions, require_permission

router = APIRouter(prefix="/v1", tags=["users"])
UsersManage = Annotated[Principal, Depends(require_permission("users:manage"))]


def _info(user: User) -> UserInfo:
    return UserInfo(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        roles=list(user.roles or []),
        permissions=list(user.permissions or []),
        effective_permissions=sorted(effective_permissions(user)),
        denied_permissions=list(user.denied_permissions or []),
        requests_per_day=user.requests_per_day,
        text_chars=user.text_chars,
        max_file_bytes=user.max_file_bytes,
        max_batch_files=user.max_batch_files,
        is_active=user.is_active,
        totp_enabled=user.totp_enabled,
    )


def _validate_grants(principal: Principal, roles: list[str], permissions: list[str]) -> None:
    unknown_roles = sorted(set(roles) - set(ROLE_TEMPLATES))
    if unknown_roles:
        raise AppError(422, "unknown_role", f"Unknown roles: {', '.join(unknown_roles)}")
    unknown_permissions = sorted(set(permissions) - set(PERMISSIONS))
    if unknown_permissions:
        raise AppError(
            422,
            "unknown_permission",
            f"Unknown permissions: {', '.join(unknown_permissions)}",
        )
    granted = set(permissions)
    for role in roles:
        granted.update(ROLE_TEMPLATES[role])
    if not granted <= set(principal.permissions):
        raise AppError(
            403,
            "permission_denied",
            "A manager cannot grant a permission they do not hold.",
        )


@router.get("/users")
async def list_users(
    principal: UsersManage,
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    rows = (
        (await session.execute(select(User).order_by(User.created_at).limit(limit))).scalars().all()
    )
    return {"data": [_info(row).model_dump(mode="json") for row in rows]}


@router.post("/users", status_code=201)
async def create_user(
    body: UserCreateRequest,
    principal: UsersManage,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserInfo:
    if not body.roles:
        body.roles = ["user"]
    _validate_grants(principal, body.roles, body.permissions)
    email = body.email.casefold().strip()
    existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        raise AppError(409, "email_exists", "A user with this email exists.")
    validate_password(body.password, email)
    now = utcnow()
    user = User(
        id=new_id("usr"),
        email=email,
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        roles=body.roles,
        permissions=body.permissions,
        denied_permissions=[],
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=principal.user_id,
            actor_type="user",
            action="user_created",
            object_type="user",
            object_id=user.id,
            detail={"roles": body.roles},
            created_at=now,
        )
    )
    await session.commit()
    return _info(user)


@router.patch("/users/{user_id}")
async def update_user(
    user_id: str,
    body: UserUpdateRequest,
    principal: UsersManage,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UserInfo:
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(404, "not_found", "The user does not exist.")
    roles = list(user.roles or []) if body.roles is None else body.roles
    permissions = list(user.permissions or []) if body.permissions is None else body.permissions
    _validate_grants(principal, roles, permissions)
    if body.display_name is not None:
        user.display_name = body.display_name
    user.roles = roles
    user.permissions = permissions
    if body.denied_permissions is not None:
        unknown = set(body.denied_permissions) - set(PERMISSIONS)
        if unknown:
            raise AppError(422, "unknown_permission", "Unknown denied permission.")
        user.denied_permissions = body.denied_permissions
    for field in ("requests_per_day", "text_chars", "max_file_bytes", "max_batch_files"):
        value = getattr(body, field)
        if value is not None:
            if value < 1:
                raise AppError(422, "invalid_limit", f"{field} must be positive.")
            setattr(user, field, value)
    if body.is_active is not None:
        user.is_active = body.is_active
    user.updated_at = utcnow()
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=principal.user_id,
            actor_type="user",
            action="user_updated",
            object_type="user",
            object_id=user.id,
            detail={"roles": roles, "permissions": permissions},
            created_at=utcnow(),
        )
    )
    await session.commit()
    return _info(user)


@router.post("/users/{user_id}/password", status_code=204)
async def reset_password(
    user_id: str,
    body: UserPasswordResetRequest,
    principal: UsersManage,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Set a new password without email and end every existing session of that user.

    ``users:manage`` is a privileged permission, so the resetter has TOTP; the target does
    not need an email address. Old sessions and TOTP recovery codes are invalidated so a
    compromised session cannot survive the reset.
    """
    user = await session.get(User, user_id)
    if user is None:
        raise AppError(404, "not_found", "The user does not exist.")
    validate_password(body.password, user.email)
    user.password_hash = hash_password(body.password)
    user.updated_at = utcnow()
    sessions = (
        await session.execute(
            select(SessionToken).where(
                SessionToken.user_id == user.id, SessionToken.revoked_at.is_(None)
            )
        )
    ).scalars()
    for token in sessions:
        token.revoked_at = utcnow()
    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=principal.user_id,
            actor_type="user",
            action="user_password_reset",
            object_type="user",
            object_id=user.id,
            detail={},
            created_at=utcnow(),
        )
    )
    await session.commit()
