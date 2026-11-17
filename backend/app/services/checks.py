"""Check job creation, execution and result serialization.

Moderation runs before a job is queued (fail closed, no unchecked pipeline entry). The
worker executes the pipeline, persists the immutable result and marks the job done.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    CheckResponse,
    FactCheckResult,
    Job,
    ModerationInfo,
    OutputModeration,
    PipelineInfo,
    WarningInfo,
)
from app.contracts.enums import JobState, TurnType
from app.core.config import Settings
from app.core.ids import new_id, utcnow
from app.db.models import Instance, ModerationEvent, Result, UsageEvent
from app.db.models import Job as JobRow
from app.llm.aliases import FS_AUDIT, FS_EXTRACT, FS_MODERATION, FS_VERIFY
from app.llm.client import LLMClient
from app.pipeline.compact import build_compact
from app.pipeline.runner import CheckPipeline, PipelineError, config_hash, refused_result
from app.rendering import RenderingService
from app.retrieval.lightrag import LightRAGClient
from app.services.language import LanguageService
from app.services.methodology import Methodology
from app.services.moderation import ModerationService
from app.services.personas import PersonaConfigError, PersonaRegistry
from app.services.publishers import PublisherRegistry


async def get_instance(session: AsyncSession) -> Instance:
    instance = (await session.execute(select(Instance).limit(1))).scalar_one_or_none()
    if instance is None:
        raise RuntimeError("instance row is missing; run the bootstrap CLI")
    return instance


def pipeline_info(
    settings: Settings,
    publishers: PublisherRegistry,
    methodology: Methodology,
    instance: Instance,
) -> PipelineInfo:
    return PipelineInfo(
        software_version="0.1.0",
        pipeline_version="1",
        corpus_version=instance.corpus_version,
        config_hash=config_hash(settings, publishers, methodology),
        publisher_list_version=publishers.version,
        embedding_model_id=None,
        models={
            "extract": FS_EXTRACT,
            "verify": FS_VERIFY,
            "audit": FS_AUDIT,
            "moderation": FS_MODERATION,
        },
        prompt_versions={"extract": "1", "verify": "1", "moderation": "1"},
    )


def result_to_row(
    result: FactCheckResult,
    *,
    user_id: str | None,
    renderings: dict[str, Any] | None = None,
) -> Result:
    return Result(
        id=result.id,
        job_id=result.job_id,
        user_id=user_id,
        version=result.version,
        previous_result_id=result.previous_version_id,
        status=result.status.value,
        preliminary=result.preliminary,
        turn_type=result.turn_type.value,
        input=result.input.model_dump(mode="json", by_alias=True),
        detected_language=result.detected_language,
        response_language=result.response_language,
        overall_verdict=result.overall_verdict.value if result.overall_verdict else None,
        overall_explanation=result.overall_explanation,
        statements=[item.model_dump(mode="json", by_alias=True) for item in result.statements],
        evidence=[item.model_dump(mode="json", by_alias=True) for item in result.evidence],
        contradictions=[
            item.model_dump(mode="json", by_alias=True) for item in result.contradictions
        ],
        argument_issues=[
            item.model_dump(mode="json", by_alias=True) for item in result.argument_issues
        ],
        clarification_questions=result.clarification_questions,
        warnings=[item.model_dump(mode="json", by_alias=True) for item in result.warnings],
        moderation=result.moderation.model_dump(mode="json", by_alias=True),
        renderings=renderings or {},
        pipeline=result.pipeline.model_dump(mode="json", by_alias=True),
        created_at=result.created_at,
        completed_at=result.completed_at,
        deleted=False,
    )


def row_to_result(row: Result) -> FactCheckResult:
    return FactCheckResult(
        id=row.id,
        job_id=row.job_id,
        version=row.version,
        previous_version_id=row.previous_result_id,
        status=row.status,
        preliminary=row.preliminary,
        turn_type=row.turn_type,
        input=row.input,
        detected_language=row.detected_language,
        response_language=row.response_language,
        overall_verdict=row.overall_verdict,
        overall_explanation=row.overall_explanation,
        statements=row.statements or [],
        evidence=row.evidence or [],
        contradictions=row.contradictions or [],
        argument_issues=row.argument_issues or [],
        clarification_questions=row.clarification_questions or [],
        moderation=row.moderation or {},
        warnings=row.warnings or [],
        pipeline=row.pipeline or {},
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


async def load_response(
    session: AsyncSession, result_id: str, *, persona_id: str | None = None
) -> CheckResponse | None:
    row = await session.get(Result, result_id)
    if row is None or row.deleted:
        return None
    result = row_to_result(row)
    compact = build_compact(result) if result.status == "complete" else None
    rendering = None
    if persona_id and row.renderings:
        raw = row.renderings.get(persona_id)
        if raw:
            from app.contracts.api import Rendering

            rendering = Rendering.model_validate(raw)
    return CheckResponse(result=result, rendering=rendering, compact=compact)


def job_to_api(row: JobRow) -> Job:
    return Job(
        id=row.id,
        kind=row.kind,
        state=row.state,
        progress=row.progress,
        result_id=row.result_id,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        poll_after_ms=500,
        events_url=f"/v1/factcheck/{row.id}/events",
        error=row.error,
    )


async def create_check_job(
    session: AsyncSession,
    *,
    settings: Settings,
    publishers: PublisherRegistry,
    methodology: Methodology,
    text: str,
    user_id: str | None,
    response_language: str | None,
    turn_type: TurnType,
    persona_id: str | None = None,
    render_model_id: str | None = None,
    output_format: str = "substance",
    render_max_tokens: int = 8000,
    render_temperature: float = 0.4,
    source_url: str | None = None,
    source_file_name: str | None = None,
    source_media_type: str | None = None,
    source_size_bytes: int | None = None,
    source_image: bool = False,
) -> tuple[JobRow, ModerationInfo]:
    moderation = await ModerationService(LLMClient(settings, consumer="moderation")).classify_check(
        text, user_id=user_id
    )
    now = utcnow()
    job_id = new_id("job")
    result_id = new_id("fc")
    instance = await get_instance(session)
    payload = {
        "text": text,
        "response_language": response_language,
        "turn_type": turn_type.value,
        "moderation": moderation.model_dump(mode="json"),
        "user_id": user_id,
        "persona_id": persona_id,
        "render_model_id": render_model_id,
        "output_format": output_format,
        "render_max_tokens": render_max_tokens,
        "render_temperature": render_temperature,
        "source_url": source_url,
        "source_file_name": source_file_name,
        "source_media_type": source_media_type,
        "source_size_bytes": source_size_bytes,
        "source_image": source_image,
    }
    job = JobRow(
        id=job_id,
        kind="check",
        state=JobState.QUEUED.value,
        payload=payload,
        progress=0.0,
        attempts=0,
        user_id=user_id,
        created_at=now,
    )
    session.add(job)
    if moderation.action == "block":
        language = response_language or "en"
        refused = refused_result(
            result_id=result_id,
            job_id=job_id,
            text=text,
            language=language,
            moderation=moderation,
            pipeline=pipeline_info(settings, publishers, methodology, instance),
            user_id=user_id,
        )
        session.add(result_to_row(refused, user_id=user_id))
        session.add(
            ModerationEvent(
                id=new_id("mod"),
                result_id=result_id,
                user_id=user_id,
                flagged=True,
                categories=moderation.categories,
                action=moderation.action.value,
                output_replaced=False,
                created_at=now,
            )
        )
        job.state = JobState.DONE.value
        job.result_id = result_id
        job.finished_at = now
        job.progress = 1.0
    await session.flush()
    return job, moderation


async def run_check_job(
    session: AsyncSession,
    *,
    settings: Settings,
    publishers: PublisherRegistry,
    methodology: Methodology,
    language: LanguageService,
    lightrag: LightRAGClient,
    personas: PersonaRegistry,
    job: JobRow,
    on_statement: Callable[[Any], Awaitable[None]] | None = None,
) -> str:
    # The worker claimed the job in another session; the instance passed here is
    # detached. Re-fetch it in this session so result_id/state updates are persisted.
    job_row = await session.get(JobRow, job.id)
    if job_row is None:
        raise PipelineError("job_missing", "The claimed job no longer exists.")
    payload = job_row.payload or {}
    text = str(payload.get("text") or "")
    if not text:
        raise PipelineError("invalid_job", "The job has no input text.")
    instance = await get_instance(session)
    moderation = ModerationInfo.model_validate(payload.get("moderation") or {})
    result_id = new_id("fc")
    pipeline = CheckPipeline(
        settings=settings,
        llm=LLMClient(settings, consumer="pipeline"),
        lightrag=lightrag,
        publishers=publishers,
        methodology=methodology,
        language=language,
        session=session,
        instance=instance,
    )
    outcome = await pipeline.run(
        result_id=result_id,
        job_id=job_row.id,
        user_id=job_row.user_id,
        text=text,
        response_language=payload.get("response_language"),
        turn_type=TurnType(payload.get("turn_type") or TurnType.NEW_CLAIM.value),
        moderation=moderation,
        source_url=payload.get("source_url"),
        source_file_name=payload.get("source_file_name"),
        source_media_type=payload.get("source_media_type"),
        source_size_bytes=payload.get("source_size_bytes"),
        source_image=bool(payload.get("source_image")),
        on_statement=on_statement,
    )
    result = outcome.result
    renderings: dict[str, Any] = {}
    persona_id = payload.get("persona_id")
    if persona_id and result.status == "complete" and payload.get("output_format") != "compact":
        try:
            render_outcome = await RenderingService(
                llm=LLMClient(settings, consumer="render", request_id=job_row.id),
                personas=personas,
                moderation=ModerationService(
                    LLMClient(settings, consumer="moderation", request_id=job_row.id)
                ),
                user_id=job_row.user_id,
            ).render(
                result,
                persona_id=str(persona_id),
                language=result.response_language,
                render_model_id=payload.get("render_model_id"),
                max_tokens=int(payload.get("render_max_tokens") or 8000),
                temperature=float(payload.get("render_temperature") or 0.4),
            )
            result.warnings.extend(render_outcome.warnings)
            renderings[str(persona_id)] = render_outcome.rendering.model_dump(mode="json")
            if render_outcome.output_moderation:
                result.moderation.output_moderation = OutputModeration.model_validate(
                    render_outcome.output_moderation
                )
        except (PersonaConfigError, KeyError, ValueError) as exc:
            result.warnings.append(
                WarningInfo(
                    code="consistency_fallback",
                    message=f"The persona rendering could not be produced: {type(exc).__name__}.",
                )
            )
    session.add(result_to_row(result, user_id=job_row.user_id, renderings=renderings))
    session.add(
        ModerationEvent(
            id=new_id("mod"),
            result_id=result_id,
            user_id=job_row.user_id,
            flagged=moderation.flagged,
            categories=moderation.categories,
            action=moderation.action.value,
            output_replaced=False,
            created_at=utcnow(),
        )
    )
    job_row.result_id = result_id
    job_row.state = JobState.DONE.value
    job_row.progress = 1.0
    job_row.finished_at = utcnow()
    await session.flush()
    return result_id


async def current_month_usage(session: AsyncSession, user_id: str) -> dict[str, Any]:
    now = utcnow()
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    tokens_in, tokens_out, cost = (
        await session.execute(
            select(
                func.coalesce(func.sum(UsageEvent.tokens_in), 0),
                func.coalesce(func.sum(UsageEvent.tokens_out), 0),
                func.coalesce(func.sum(UsageEvent.cost_usd), 0),
            ).where(UsageEvent.created_at >= start, UsageEvent.user_id == user_id)
        )
    ).one()
    return {"tokens_in": int(tokens_in), "tokens_out": int(tokens_out), "cost": Decimal(cost)}


def request_hash(payload: dict[str, Any]) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
    )
