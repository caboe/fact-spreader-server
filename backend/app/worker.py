"""Pipeline worker (PROTOCOL §4.1, IMPLEMENT Phase 1).

Claims jobs with ``FOR UPDATE SKIP LOCKED``, processes one at a time, and keeps failed or
retryable jobs visible. Partial result durability arrives with the Phase 2 SSE work; the
result row itself is already durable.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import os
import signal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.ids import new_id, utcnow
from app.core.logging import configure_logging
from app.db.models import Job as JobRow
from app.db.models import JobEvent
from app.db.session import Database
from app.llm.client import LLMError
from app.pipeline.runner import PipelineError
from app.retrieval.lightrag import LightRAGClient
from app.services.checks import run_check_job
from app.services.documents import run_document_index_job
from app.services.language import LanguageService
from app.services.methodology import Methodology
from app.services.personas import PersonaRegistry
from app.services.publisher_overrides import effective_publishers

logger = logging.getLogger("app.worker")


async def claim_job(session: AsyncSession, worker_id: str) -> JobRow | None:
    statement = (
        select(JobRow)
        .where(JobRow.state == "queued")
        .order_by(JobRow.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    job = (await session.execute(statement)).scalar_one_or_none()
    if job is None:
        return None
    job.state = "running"
    job.started_at = utcnow()
    job.locked_by = worker_id
    job.locked_at = utcnow()
    job.attempts = int(job.attempts or 0) + 1
    await session.commit()
    return job


async def fail_or_retry(
    session: AsyncSession, job_id: str, *, code: str, detail: str, retryable: bool
) -> None:
    job = await session.get(JobRow, job_id)
    if job is None:
        return
    job.error = {"code": code, "message": detail[:500], "retryable": retryable}
    if retryable and int(job.attempts or 0) < 3:
        job.state = "queued"
        job.locked_by = None
        job.locked_at = None
        job.started_at = None
    else:
        job.state = "failed"
        job.finished_at = utcnow()
    await session.commit()


async def run_once(database: Database, settings: Settings, worker_id: str) -> bool:
    async with database.session_factory() as claim_session:
        job = await claim_job(claim_session, worker_id)
    if job is None:
        return False
    logger.info("job_claimed", extra={"event": "job", "job_id": job.id})
    async with database.session_factory() as sequence_session:
        last_seq = int(
            (
                await sequence_session.execute(
                    select(func.coalesce(func.max(JobEvent.seq), 0)).where(
                        JobEvent.job_id == job.id
                    )
                )
            ).scalar_one()
        )
    sequence = [last_seq]

    async def emit_statement(statement: Any) -> None:
        sequence[0] += 1
        async with database.session_factory() as event_session:
            event_session.add(
                JobEvent(
                    id=new_id("evt"),
                    job_id=job.id,
                    seq=sequence[0],
                    event_type="statement",
                    data=statement.model_dump(mode="json", by_alias=True),
                    created_at=utcnow(),
                )
            )
            await event_session.commit()

    async with database.session_factory() as session:
        try:
            if job.kind == "document_index":
                await run_document_index_job(
                    session,
                    settings=settings,
                    lightrag=LightRAGClient(settings),
                    job=job,
                )
                await session.commit()
                logger.info("job_done", extra={"event": "job", "job_id": job.id})
                return True
            result_id = await run_check_job(
                session,
                settings=settings,
                publishers=await effective_publishers(session, settings.publisher_list_path),
                methodology=Methodology.load(settings.checklist_dir, settings.pattern_list_path),
                language=LanguageService(
                    settings.supported_languages, settings.default_response_language
                ),
                lightrag=LightRAGClient(settings),
                personas=PersonaRegistry.from_path(settings.personas_path),
                job=job,
                on_statement=emit_statement,
            )
            await session.commit()
            logger.info(
                "job_done", extra={"event": "job", "job_id": job.id, "result_id": result_id}
            )
        except PipelineError as exc:
            await session.rollback()
            async with database.session_factory() as fail_session:
                await fail_or_retry(
                    fail_session,
                    job.id,
                    code=exc.code,
                    detail=exc.detail,
                    retryable=exc.retryable,
                )
            logger.warning("job_failed", extra={"event": "job", "job_id": job.id})
        except LLMError as exc:
            await session.rollback()
            async with database.session_factory() as fail_session:
                await fail_or_retry(
                    fail_session,
                    job.id,
                    code=exc.code,
                    detail=exc.detail,
                    retryable=(
                        exc.code != "invalid_model_output"
                        and (exc.status >= 500 or exc.status == 429)
                    ),
                )
            logger.warning("job_llm_failed", extra={"event": "job", "job_id": job.id})
        except Exception as exc:
            await session.rollback()
            logger.exception("job_crashed", extra={"event": "job", "job_id": job.id})
            async with database.session_factory() as fail_session:
                await fail_or_retry(
                    fail_session,
                    job.id,
                    code="internal_error",
                    detail=type(exc).__name__,
                    retryable=False,
                )
    return True


async def main_async(poll_interval: float, once: bool) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    database = Database(settings)
    worker_id = f"{os.uname().nodename}:{os.getpid()}:{new_id('wrk')}"
    stop = asyncio.Event()

    def _stop(*_: object) -> None:
        stop.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    try:
        while not stop.is_set():
            processed = await run_once(database, settings, worker_id)
            if once:
                return
            if not processed:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), timeout=poll_interval)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fact Spreader pipeline worker")
    parser.add_argument("--once", action="store_true", help="process at most one job and exit")
    parser.add_argument("--poll-interval", type=float, default=1.0)
    args = parser.parse_args()
    asyncio.run(main_async(args.poll_interval, args.once))


if __name__ == "__main__":
    main()
