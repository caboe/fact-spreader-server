"""Retention redacts old context and deletes old job events (IMPLEMENT Phase 5)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from app.core.ids import new_id, utcnow
from app.db.models import AuditLog, Job, JobEvent, Result, UsageEvent, UsageRollup
from app.services.retention import run_retention
from sqlalchemy import select

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_retention_redacts_old_context_and_deletes_old_job_events(
    app: Any, settings: Any
) -> None:
    old = utcnow() - timedelta(days=200)
    async with app.state.db.session_factory() as session:
        job = Job(
            id=new_id("job"),
            kind="check",
            state="done",
            payload={},
            progress=1.0,
            created_at=old,
            started_at=old,
            finished_at=old,
        )
        no_result_job = Job(
            id=new_id("job"),
            kind="check",
            state="done",
            payload={},
            progress=1.0,
            created_at=old,
            started_at=old,
            finished_at=old,
        )
        session.add_all([job, no_result_job])
        await session.flush()
        session.add(
            Result(
                id=new_id("fc"),
                job_id=job.id,
                version=1,
                status="complete",
                preliminary=False,
                turn_type="new_claim",
                input={
                    "type": "text",
                    "text": "A retained claim.",
                    "context": {"messages": [{"role": "user", "content": "private"}]},
                },
                detected_language="en",
                response_language="en",
                overall_verdict="true",
                statements=[],
                evidence=[],
                contradictions=[],
                argument_issues=[],
                clarification_questions=[],
                warnings=[],
                moderation={},
                pipeline={},
                created_at=old,
                completed_at=old,
                deleted=False,
            )
        )
        session.add(
            JobEvent(
                id=new_id("evt"),
                job_id=no_result_job.id,
                seq=1,
                event_type="state",
                data={},
                created_at=old,
            )
        )
        await session.commit()
        old_job_id = no_result_job.id
        job_event_id = (
            await session.execute(select(JobEvent.id).where(JobEvent.job_id == no_result_job.id))
        ).scalar_one()
        result_id = (
            await session.execute(select(Result.id).where(Result.created_at == old))
        ).scalar_one()
    recent = utcnow() - timedelta(days=2)
    async with app.state.db.session_factory() as session:
        for _ in range(2):
            session.add(
                UsageEvent(
                    id=new_id("use"),
                    request_id=None,
                    user_id=None,
                    api_key_id=None,
                    consumer="pipeline",
                    role="verify",
                    provider="deepseek",
                    model="deepseek-chat",
                    tokens_in=100,
                    tokens_out=10,
                    cost_usd=0.001,
                    cost_estimated=False,
                    latency_ms=10,
                    status=200,
                    data_classes=[],
                    created_at=old,
                )
            )
        session.add(
            UsageEvent(
                id=new_id("use"),
                request_id=None,
                user_id=None,
                api_key_id=None,
                consumer="pipeline",
                role="verify",
                provider="deepseek",
                model="deepseek-chat",
                tokens_in=5,
                tokens_out=1,
                cost_usd=0.0001,
                cost_estimated=False,
                latency_ms=10,
                status=200,
                data_classes=[],
                created_at=recent,
            )
        )
        await session.commit()
    async with app.state.db.session_factory() as session:
        report = await run_retention(session, settings, dry_run=True)
    assert report.dry_run is True
    assert report.contexts_redacted == 1
    assert report.usage_events_rolled_up == 2
    async with app.state.db.session_factory() as session:
        untouched = await session.get(Result, result_id)
        assert untouched is not None
        assert untouched.input["context"] is not None
        dry_audit = (
            (
                await session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "retention_run",
                        AuditLog.detail["dry_run"].astext == "true",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(dry_audit) == 1
        assert await session.get(JobEvent, job_event_id) is not None
    async with app.state.db.session_factory() as session:
        report = await run_retention(session, settings)
    assert report.usage_events_rolled_up == 2
    assert report.usage_events_deleted == 2
    assert report.contexts_redacted == 1
    assert report.job_events_deleted == 1
    assert report.jobs_deleted == 1
    async with app.state.db.session_factory() as session:
        result = await session.get(Result, result_id)
        assert result is not None
        assert result.input["text"] == "A retained claim."
        assert result.input["context"] is None
        assert result.input["context_redacted"] is True
        assert await session.get(Job, old_job_id) is None
        rollups = (await session.execute(select(UsageRollup))).scalars().all()
        assert len(rollups) == 1
        assert rollups[0].events == 2
        assert rollups[0].tokens_in == 200
        assert rollups[0].tokens_out == 20
        assert float(rollups[0].cost_usd) == pytest.approx(0.002)
        remaining_events = (await session.execute(select(UsageEvent))).scalars().all()
        assert len(remaining_events) == 1
        assert remaining_events[0].created_at == recent
