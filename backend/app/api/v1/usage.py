"""Own usage and budget (PROTOCOL §10, quantities only)."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import UsageMe
from app.db.models import Job as JobRow
from app.db.models import User
from app.db.session import get_session
from app.services.auth import Principal, current_principal
from app.services.checks import current_month_usage

router = APIRouter(prefix="/v1/usage", tags=["usage"])
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


@router.get("/me", response_model=UsageMe)
async def my_usage(
    request: Request,
    principal: CurrentPrincipal,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> UsageMe:
    now = datetime.now(UTC)
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    usage = await current_month_usage(session, principal.user_id)
    check_count = (
        await session.execute(
            select(func.count(JobRow.id)).where(
                JobRow.user_id == principal.user_id,
                JobRow.kind == "check",
                JobRow.created_at >= start,
            )
        )
    ).scalar_one()
    user = await session.get(User, principal.user_id)
    budget = (
        float(user.llm_budget_usd) if user else float(request.app.state.settings.user_budget_usd)
    )
    remaining = max(0.0, budget - float(usage["cost"]))
    channel = "api" if principal.via == "api_key" else "web"
    return UsageMe(
        period={"from": start.date().isoformat(), "to": now.date().isoformat()},
        requests={"total": int(check_count), "by_channel": {channel: int(check_count)}},
        checks={"total": int(check_count), "fast": 0, "full": int(check_count), "rejected": 0},
        llm={
            "tokens_in": int(usage["tokens_in"]),
            "tokens_out": int(usage["tokens_out"]),
            "cost_usd": float(Decimal(usage["cost"])),
        },
        limits={
            "requests_per_day": None,
            "llm_budget_usd_month": budget,
            "text_chars": request.app.state.settings.max_text_chars,
        },
        budget={"remaining_usd": round(remaining, 6), "resets_at": _reset_iso(now)},
        rejected={"rate_limit": 0, "budget": 0, "moderation": 0},
    )


def _reset_iso(now: datetime) -> str:
    if now.month == 12:
        reset = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        reset = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    return reset.isoformat().replace("+00:00", "Z")
