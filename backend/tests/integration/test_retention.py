"""Retention redacts old context and deletes old job events (IMPLEMENT Phase 5)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from app.core.ids import new_id, utcnow
from app.db.models import Job, JobEvent, Result
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
        result_id = (
            await session.execute(select(Result.id).where(Result.created_at == old))
        ).scalar_one()
    async with app.state.db.session_factory() as session:
        report = await run_retention(session, settings)
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
