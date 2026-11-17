"""Web session login and identity. The product API remains /v1; this is the browser shell."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.ids import utcnow
from app.core.security import hash_token, verify_password
from app.db.models import SessionToken, User
from app.db.session import get_session
from app.services.auth import (
    SESSION_COOKIE,
    SESSION_HOURS,
    TOTP_ISSUER,
    Principal,
    authenticate_password,
    create_session,
    current_principal,
    decrypt_totp_secret,
    encrypt_totp_secret,
    hash_ip,
    new_recovery_codes,
    totp_required,
    verify_totp,
)

router = APIRouter(prefix="/api", tags=["web-auth"])
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=500)
    totp_code: str | None = Field(default=None, max_length=64)


class TotpConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=64)


class TotpDisableRequest(BaseModel):
    password: str = Field(min_length=1, max_length=500)
    code: str = Field(min_length=6, max_length=64)


@router.post("/auth/login")
async def login(
    body: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    user = await authenticate_password(session, body.email, body.password)
    if user is None:
        raise AppError(401, "invalid_credentials", "Email or password is incorrect.")
    setup_required = totp_required(user.permissions) and not user.totp_enabled
    if user.totp_enabled:
        if not body.totp_code:
            raise AppError(403, "totp_required", "A TOTP code is required for this account.")
        valid, recovery = verify_totp(user, body.totp_code, request.app.state.settings)
        if not valid:
            raise AppError(401, "invalid_totp", "The TOTP or recovery code is invalid.")
        if recovery:
            await session.commit()
    client = request.client.host if request.client else "unknown"
    _token, raw, csrf = await create_session(
        session,
        user=user,
        user_agent=request.headers.get("User-Agent"),
        ip_hash=hash_ip(client, request.app.state.settings.app_secret_key.get_secret_value()),
    )
    await session.commit()
    payload = {
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "permissions": user.permissions,
        },
        "csrf_token": csrf,
        "totp_setup_required": setup_required,
    }
    json_response = JSONResponse(content=payload)
    json_response.set_cookie(
        SESSION_COOKIE,
        raw,
        httponly=True,
        secure=request.app.state.settings.is_production,
        samesite="lax",
        max_age=SESSION_HOURS * 3600,
        path="/",
    )
    return json_response


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        row = (
            await session.execute(
                select(SessionToken).where(SessionToken.token_hash == hash_token(cookie))
            )
        ).scalar_one_or_none()
        if row is not None:
            row.revoked_at = utcnow()
            await session.commit()
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


async def _load_user(session: AsyncSession, principal: Principal) -> User:
    user = await session.get(User, principal.user_id)
    if user is None or not user.is_active:
        raise AppError(401, "authentication_required", "The user is not active.")
    return user


@router.post("/auth/totp/setup")
async def totp_setup(
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, str]:
    import pyotp

    user = await _load_user(session, principal)
    secret = pyotp.random_base32()
    user.totp_secret_enc = encrypt_totp_secret(request.app.state.settings, secret)
    user.totp_enabled = False
    user.updated_at = utcnow()
    await session.commit()
    uri = pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=TOTP_ISSUER)
    return {"secret": secret, "otpauth_uri": uri}


@router.post("/auth/totp/confirm")
async def totp_confirm(
    body: TotpConfirmRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, object]:
    import pyotp

    user = await _load_user(session, principal)
    if not user.totp_secret_enc:
        raise AppError(422, "totp_not_setup", "Start TOTP setup first.")
    secret = decrypt_totp_secret(request.app.state.settings, user.totp_secret_enc)
    if not pyotp.TOTP(secret).verify(body.code.strip(), valid_window=1):
        raise AppError(401, "invalid_totp", "The TOTP code is invalid.")
    plain, hashed = new_recovery_codes()
    user.totp_enabled = True
    user.totp_recovery_codes = hashed
    user.updated_at = utcnow()
    await session.commit()
    return {"enabled": True, "recovery_codes": plain}


@router.post("/auth/totp/disable")
async def totp_disable(
    body: TotpDisableRequest,
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, bool]:
    user = await _load_user(session, principal)
    if not verify_password(body.password, user.password_hash):
        raise AppError(401, "invalid_credentials", "The password is incorrect.")
    valid, _recovery = verify_totp(user, body.code, request.app.state.settings)
    if not valid:
        raise AppError(401, "invalid_totp", "The TOTP or recovery code is invalid.")
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_recovery_codes = []
    user.updated_at = utcnow()
    await session.commit()
    return {"enabled": False}


@router.get("/me")
async def me(principal: CurrentPrincipal) -> dict[str, object]:
    return {
        "id": principal.user_id,
        "email": principal.email,
        "display_name": principal.display_name,
        "permissions": sorted(principal.permissions),
        "via": principal.via,
    }
