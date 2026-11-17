"""Authentication and server-side permission checks (PROTOCOL §1.1)."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.enums import PERMISSIONS
from app.core.config import Settings
from app.core.errors import AppError, permission_denied
from app.core.ids import new_id, utcnow
from app.core.security import (
    hash_password,
    hash_token,
    new_api_key,
    new_csrf_token,
    verify_password,
)
from app.db.models import ApiKey, SessionToken, User
from app.db.session import get_session

SESSION_COOKIE = "fs_session"
SESSION_HOURS = 12


@dataclass(frozen=True)
class Principal:
    user_id: str
    principal_id: str
    email: str
    display_name: str
    permissions: frozenset[str]
    api_key_id: str | None = None
    via: str = "session"

    def has(self, permission: str) -> bool:
        return permission in self.permissions


def _authentication_error(detail: str) -> AppError:
    return AppError(
        401,
        "authentication_required",
        detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def authenticate(request: Request, session: AsyncSession) -> Principal:
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        return await _authenticate_token(session, token)
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        return await _authenticate_session(request, session, cookie)
    raise _authentication_error("A bearer token or session is required.")


async def _authenticate_token(session: AsyncSession, token: str) -> Principal:
    if token.startswith("fc_dev_"):
        raise AppError(403, "device_token_not_supported", "Device tokens arrive in Phase 5.")
    if not token.startswith("fc_live_"):
        raise _authentication_error("Unknown credential type.")
    row = (
        await session.execute(
            select(ApiKey, User)
            .join(User, User.id == ApiKey.user_id)
            .where(ApiKey.key_hash == hash_token(token))
        )
    ).first()
    if row is None:
        raise _authentication_error("The API key is invalid.")
    key, user = row
    now = utcnow()
    if key.revoked_at is not None or (key.expires_at is not None and key.expires_at <= now):
        raise _authentication_error("The API key is expired or revoked.")
    if not user.is_active:
        raise _authentication_error("The user is inactive.")
    permissions = frozenset(key.permissions) & frozenset(user.permissions)
    key.last_used_at = now
    return Principal(
        user_id=user.id,
        principal_id=f"key_{key.id}",
        email=user.email,
        display_name=user.display_name,
        permissions=permissions,
        api_key_id=key.id,
        via="api_key",
    )


async def _authenticate_session(request: Request, session: AsyncSession, cookie: str) -> Principal:
    row = (
        await session.execute(
            select(SessionToken, User)
            .join(User, User.id == SessionToken.user_id)
            .where(SessionToken.token_hash == hash_token(cookie))
        )
    ).first()
    if row is None:
        raise _authentication_error("The session is invalid.")
    token, user = row
    now = utcnow()
    if token.revoked_at is not None or token.expires_at <= now:
        raise _authentication_error("The session is expired.")
    if not user.is_active:
        raise _authentication_error("The user is inactive.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("X-CSRF-Token", "")
        if not csrf or csrf != token.csrf_token:
            raise AppError(403, "csrf_failed", "The CSRF token is missing or invalid.")
    token.last_seen_at = now
    return Principal(
        user_id=user.id,
        principal_id=f"usr_{user.id}",
        email=user.email,
        display_name=user.display_name,
        permissions=frozenset(user.permissions),
        via="session",
    )


def require_permission(permission: str) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        request: Request,
        session: Annotated[AsyncSession, Depends(get_session)],
    ) -> Principal:
        principal = await authenticate(request, session)
        if not principal.has(permission):
            raise permission_denied(f"The credential needs {permission}.")
        return principal

    return dependency


async def current_principal(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    return await authenticate(request, session)


async def create_api_key(
    session: AsyncSession,
    *,
    user: User,
    name: str,
    permissions: list[str] | None = None,
) -> tuple[ApiKey, str]:
    plaintext, prefix, digest = new_api_key()
    now = utcnow()
    key = ApiKey(
        id=new_id("key"),
        user_id=user.id,
        name=name,
        key_hash=digest,
        key_prefix=prefix,
        permissions=permissions if permissions is not None else list(user.permissions),
        created_at=now,
    )
    session.add(key)
    await session.flush()
    return key, plaintext


async def create_session(
    session: AsyncSession,
    *,
    user: User,
    user_agent: str | None,
    ip_hash: str | None,
) -> tuple[SessionToken, str, str]:
    raw = new_csrf_token() + new_csrf_token()
    csrf = new_csrf_token()
    now = utcnow()
    token = SessionToken(
        id=new_id("ses"),
        user_id=user.id,
        token_hash=hash_token(raw),
        csrf_token=csrf,
        user_agent=(user_agent or "")[:500] or None,
        ip_hash=ip_hash,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(hours=SESSION_HOURS),
    )
    session.add(token)
    await session.flush()
    return token, raw, csrf


async def authenticate_password(session: AsyncSession, email: str, password: str) -> User | None:
    user = (
        await session.execute(select(User).where(User.email == email.casefold().strip()))
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        return None
    return user


def all_permissions() -> list[str]:
    return list(PERMISSIONS)


def hash_ip(ip: str, secret: str) -> str:
    return hashlib.sha256(f"{secret}:{ip}".encode()).hexdigest()


def make_password_hash(password: str) -> str:
    return hash_password(password)


def user_is_privileged(principal: Principal) -> bool:
    return bool(
        principal.permissions
        & {"config:manage", "users:manage", "documents:review", "quality:read"}
    )


def settings_supported_languages(settings: Settings) -> list[str]:
    return list(settings.supported_languages)
