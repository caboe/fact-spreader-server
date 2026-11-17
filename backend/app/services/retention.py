"""Retention jobs for context metadata, job events and terminal jobs.

Context text is redacted from old results while the result row and its verdict stay; job
events and terminal job rows without a result are deleted. Usage events older than the
configured period are aggregated into monthly rollups (bucketed by user, consumer,
provider and model), then the detail events are purged; the aggregate keeps costs and
counts, never contents. Every run writes an audit row with counts, including a dry run.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import delete, exists, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.ids import new_id, utcnow
from app.db.models import AuditLog, Job, JobEvent, Result, UsageEvent, UsageRollup

logger = logging.getLogger(__name__)


@dataclass
class RetentionReport:
    contexts_redacted: int = 0
    job_events_deleted: int = 0
    jobs_deleted: int = 0
    usage_events_rolled_up: int = 0
    usage_events_deleted: int = 0
    dry_run: bool = False

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "contexts_redacted": self.contexts_redacted,
            "job_events_deleted": self.job_events_deleted,
            "jobs_deleted": self.jobs_deleted,
            "usage_events_rolled_up": self.usage_events_rolled_up,
            "usage_events_deleted": self.usage_events_deleted,
            "dry_run": self.dry_run,
        }


async def run_retention(
    session: AsyncSession, settings: Settings, *, dry_run: bool = False
) -> RetentionReport:
    now = utcnow()
    context_cutoff = now - timedelta(days=settings.context_retention_days)
    event_cutoff = now - timedelta(days=settings.job_event_retention_days)
    job_cutoff = now - timedelta(days=settings.job_retention_days)
    report = RetentionReport(dry_run=dry_run)

    rows = (
        (
            await session.execute(
                select(Result).where(
                    Result.created_at < context_cutoff,
                    Result.deleted.is_(False),
                    Result.input["context"].isnot(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        payload = dict(row.input or {})
        if payload.get("context") is None:
            continue
        report.contexts_redacted += 1
        if dry_run:
            continue
        payload["context"] = None
        payload["context_redacted"] = True
        row.input = payload
    if rows and not dry_run:
        await session.flush()

    event_query = select(JobEvent.id).where(JobEvent.created_at < event_cutoff)
    if dry_run:
        report.job_events_deleted = len((await session.execute(event_query)).scalars().all())
    else:
        event_result = cast(
            CursorResult[Any],
            await session.execute(delete(JobEvent).where(JobEvent.created_at < event_cutoff)),
        )
        report.job_events_deleted = int(event_result.rowcount or 0)

    job_query = select(Job.id).where(
        Job.created_at < job_cutoff,
        Job.state.in_(["done", "failed", "cancelled"]),
        ~exists().where(Result.job_id == Job.id),
    )
    usage_cutoff = now - timedelta(days=settings.usage_event_retention_days)
    await _rollup_usage(session, usage_cutoff, report, dry_run=dry_run)

    job_ids = (await session.execute(job_query)).scalars().all()
    report.jobs_deleted = len(job_ids)
    if job_ids and not dry_run:
        await session.execute(delete(Job).where(Job.id.in_(job_ids)))

    session.add(
        AuditLog(
            id=new_id("aud"),
            actor_id=None,
            actor_type="system",
            action="retention_run",
            object_type="retention",
            object_id=None,
            detail=report.as_dict(),
            created_at=now,
        )
    )
    # A dry run commits only its audit row: it never assigned redacted payloads above.
    await session.commit()
    logger.info("retention_run %s", report.as_dict())
    return report


async def _rollup_usage(
    session: AsyncSession,
    cutoff: Any,
    report: RetentionReport,
    *,
    dry_run: bool,
) -> None:
    month = func.date_trunc("month", UsageEvent.created_at).label("month")
    rows = (
        await session.execute(
            select(
                month,
                UsageEvent.user_id,
                UsageEvent.consumer,
                UsageEvent.provider,
                UsageEvent.model,
                func.count(UsageEvent.id),
                func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                func.coalesce(func.sum(UsageEvent.tokens_out), 0),
                func.coalesce(func.sum(UsageEvent.cost_usd), 0),
            )
            .where(UsageEvent.created_at < cutoff)
            .group_by(
                month,
                UsageEvent.user_id,
                UsageEvent.consumer,
                UsageEvent.provider,
                UsageEvent.model,
            )
        )
    ).all()
    report.usage_events_rolled_up = sum(int(row[5]) for row in rows)
    if dry_run:
        return
    for row in rows:
        month_value = row[0].date() if hasattr(row[0], "date") else row[0]
        user_key = str(row[1] or "")
        existing = (
            await session.execute(
                select(UsageRollup).where(
                    UsageRollup.month == month_value,
                    UsageRollup.user_id == user_key,
                    UsageRollup.consumer == row[2],
                    UsageRollup.provider == row[3],
                    UsageRollup.model == row[4],
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                UsageRollup(
                    id=new_id("url"),
                    month=month_value,
                    user_id=user_key,
                    consumer=str(row[2]),
                    provider=str(row[3]),
                    model=str(row[4]),
                    events=int(row[5]),
                    tokens_in=int(row[6]),
                    tokens_out=int(row[7]),
                    cost_usd=Decimal(row[8]),
                    created_at=utcnow(),
                )
            )
        else:
            existing.events += int(row[5])
            existing.tokens_in += int(row[6])
            existing.tokens_out += int(row[7])
            existing.cost_usd = Decimal(existing.cost_usd) + Decimal(row[8])
    result = cast(
        CursorResult[Any],
        await session.execute(delete(UsageEvent).where(UsageEvent.created_at < cutoff)),
    )
    report.usage_events_deleted = int(result.rowcount or 0)
