"""Retention jobs for context metadata, job events and terminal jobs.

Context text is redacted from old results while the result row and its verdict stay; job
events and terminal job rows without a result are deleted. Every run writes an audit row
with counts, including a dry run. Usage events are intentionally left for a later rollup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, cast

from sqlalchemy import delete, exists, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.ids import new_id, utcnow
from app.db.models import AuditLog, Job, JobEvent, Result

logger = logging.getLogger(__name__)


@dataclass
class RetentionReport:
    contexts_redacted: int = 0
    job_events_deleted: int = 0
    jobs_deleted: int = 0
    dry_run: bool = False

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "contexts_redacted": self.contexts_redacted,
            "job_events_deleted": self.job_events_deleted,
            "jobs_deleted": self.jobs_deleted,
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
        payload["context"] = None
        payload["context_redacted"] = True
        row.input = payload
        report.contexts_redacted += 1
        if dry_run:
            continue
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
    if not dry_run:
        await session.commit()
    logger.info("retention_run %s", report.as_dict())
    return report
