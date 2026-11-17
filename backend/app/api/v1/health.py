"""Liveness and readiness (PURPOSE §4.2).

Readiness checks the dependencies the Phase 1 slice needs: Postgres, Redis, stock
LightRAG, and a configured moderation alias. It never checks a provider with a paid call.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.db.models import ModelRecord

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "fact-spreader", "version": "0.1.0"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    components: dict[str, bool] = {}
    session_factory = request.app.state.db.session_factory
    try:
        async with session_factory() as session:
            await session.execute(select(1))
            moderation = (
                await session.execute(
                    select(ModelRecord.id).where(ModelRecord.gateway_alias == "fs-moderation")
                )
            ).scalar_one_or_none()
            components["database"] = True
            components["moderation"] = moderation is not None
    except Exception:
        components["database"] = False
        components["moderation"] = False
    try:
        components["redis"] = bool(await request.app.state.redis.ping())
    except Exception:
        components["redis"] = False
    try:
        components["lightrag"] = await request.app.state.lightrag.health()
    except Exception:
        components["lightrag"] = False
    ready = all(components.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "components": components},
    )
