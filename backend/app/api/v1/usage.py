"""Usage: own budget and operator summaries (PROTOCOL §10, hard invariant 16).

Summaries contain quantities only: counts, tokens and costs grouped by day, consumer,
role, provider and model. No claim text, user identity or request id is ever returned.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import UsageMe, UsageSummary
from app.db.models import Job as JobRow
from app.db.models import UsageEvent, User
from app.db.session import get_session
from app.services.auth import Principal, current_principal, require_permission
from app.services.checks import current_month_usage

router = APIRouter(prefix="/v1/usage", tags=["usage"])
CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
UsageRead = Annotated[Principal, Depends(require_permission("usage:read"))]
SessionDep = Annotated[AsyncSession, Depends(get_session)]

_BREAKDOWNS = ("consumer", "role", "provider", "model")
CSV_COLUMNS = (
    "date",
    "consumer",
    "role",
    "provider",
    "model",
    "calls",
    "tokens_in",
    "tokens_out",
    "cost_usd",
)


@router.get("/me", response_model=UsageMe)
async def my_usage(
    request: Request,
    principal: CurrentPrincipal,
    session: SessionDep,
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


def _date_range(from_date: date | None, to_date: date | None) -> tuple[datetime, datetime]:
    today = datetime.now(UTC).date()
    start_date = from_date or today.replace(day=1)
    end_date = to_date or today
    start = datetime.combine(start_date, time.min, tzinfo=UTC)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
    return start, end


async def _day_rows(session: AsyncSession, start: datetime, end: datetime) -> list[Any]:
    day = func.date_trunc("day", UsageEvent.created_at).label("day")
    return list(
        (
            await session.execute(
                select(
                    day,
                    UsageEvent.consumer,
                    UsageEvent.role,
                    UsageEvent.provider,
                    UsageEvent.model,
                    func.count(UsageEvent.id),
                    func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                    func.coalesce(func.sum(UsageEvent.tokens_out), 0),
                    func.coalesce(func.sum(UsageEvent.cost_usd), 0),
                )
                .where(UsageEvent.created_at >= start, UsageEvent.created_at < end)
                .group_by(
                    day, UsageEvent.consumer, UsageEvent.role, UsageEvent.provider, UsageEvent.model
                )
                .order_by(day)
            )
        ).all()
    )


def _row_dict(row: Any) -> dict[str, Any]:
    month_or_day = row[0]
    day = month_or_day.date() if hasattr(month_or_day, "date") else month_or_day
    return {
        "date": day.isoformat() if isinstance(day, date) else str(day),
        "consumer": row[1],
        "role": row[2],
        "provider": row[3],
        "model": row[4],
        "calls": int(row[5]),
        "tokens_in": int(row[6]),
        "tokens_out": int(row[7]),
        "cost_usd": float(Decimal(row[8])),
    }


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "calls": sum(row["calls"] for row in rows),
        "tokens_in": sum(row["tokens_in"] for row in rows),
        "tokens_out": sum(row["tokens_out"] for row in rows),
        "cost_usd": round(sum(row["cost_usd"] for row in rows), 6),
    }


@router.get("/summary", response_model=UsageSummary)
async def usage_summary(
    principal: UsageRead,
    session: SessionDep,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
) -> UsageSummary:
    start, end = _date_range(from_date, to_date)
    rows = [_row_dict(row) for row in await _day_rows(session, start, end)]
    series: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = series.setdefault(
            row["date"],
            {"date": row["date"], "calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0},
        )
        bucket["calls"] += row["calls"]
        bucket["tokens_in"] += row["tokens_in"]
        bucket["tokens_out"] += row["tokens_out"]
        bucket["cost_usd"] = round(bucket["cost_usd"] + row["cost_usd"], 6)
    breakdowns: dict[str, list[dict[str, Any]]] = {}
    for field in _BREAKDOWNS:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(str(row[field]), []).append(row)
        breakdowns[field] = [
            {"key": key, **_aggregate(items)} for key, items in sorted(grouped.items())
        ]
    counts = (
        await session.execute(
            select(JobRow.kind, func.count(JobRow.id))
            .where(JobRow.created_at >= start, JobRow.created_at < end)
            .group_by(JobRow.kind)
        )
    ).all()
    cards = {str(kind): int(count) for kind, count in counts}
    return UsageSummary(
        period={
            "from": start.date().isoformat(),
            "to": (end.date() - timedelta(days=1)).isoformat(),
        },
        totals=_aggregate(rows),
        cards=cards,
        series=list(series.values()),
        breakdowns=breakdowns,
    )


@router.get(
    "/summary.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
async def usage_summary_csv(
    principal: UsageRead,
    session: SessionDep,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
) -> Response:
    start, end = _date_range(from_date, to_date)
    rows = [_row_dict(row) for row in await _day_rows(session, start, end)]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row[column] for column in CSV_COLUMNS})
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="usage-{start.date().isoformat()}-'
                f'{(end.date() - timedelta(days=1)).isoformat()}.csv"'
            )
        },
    )


def _reset_iso(now: datetime) -> str:
    if now.month == 12:
        reset = datetime(now.year + 1, 1, 1, tzinfo=UTC)
    else:
        reset = datetime(now.year, now.month + 1, 1, tzinfo=UTC)
    return reset.isoformat().replace("+00:00", "Z")
