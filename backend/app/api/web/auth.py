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
from app.core.security import hash_token
from app.db.models import SessionToken
from app.db.session import get_session
from app.services.auth import (
    SESSION_COOKIE,
    SESSION_HOURS,
    Principal,
    authenticate_password,
    create_session,
    current_principal,
    hash_ip,
)

router = APIRouter(prefix="/api", tags=["web-auth"])
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=500)


@router.post("/auth/login")
async def login(
    body: LoginRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JSONResponse:
    user = await authenticate_password(session, body.email, body.password)
    if user is None:
        raise AppError(401, "invalid_credentials", "Email or password is incorrect.")
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


@router.get("/me")
async def me(principal: CurrentPrincipal) -> dict[str, object]:
    return {
        "id": principal.user_id,
        "email": principal.email,
        "display_name": principal.display_name,
        "permissions": sorted(principal.permissions),
        "via": principal.via,
    }
