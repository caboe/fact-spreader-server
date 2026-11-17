"""Fast path: a preliminary answer while the full check runs (IMPLEMENT Phase 3).

A cache hit reuses a gated full result from the same corpus version. A miss extracts the
input's statements with a bounded call and returns them without a verdict; the full check
is already queued and becomes the next version. The preliminary never invents a verdict
and never reuses a result from another corpus version or response language.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.api import (
    CheckResponse,
    FactCheckResult,
    InputInfo,
    PipelineInfo,
    Statement,
    WarningInfo,
)
from app.contracts.enums import ResultStatus, TurnType
from app.core.config import Settings
from app.core.ids import new_id, normalize_text, sha256_text, utcnow
from app.db.models import Job as JobRow
from app.db.models import Result
from app.llm.client import LLMClient, LLMError
from app.pipeline.compact import build_compact
from app.pipeline.extraction import extract_statements
from app.services.checks import (
    get_instance,
    pipeline_info,
    result_to_row,
    row_to_result,
)
from app.services.claim_cache import lookup as cache_lookup
from app.services.language import LanguageService
from app.services.methodology import Methodology
from app.services.publishers import PublisherRegistry

logger = logging.getLogger(__name__)

_PRELIMINARY_TEXT = {
    "en": "Preliminary check: the full check is still running.",
    "de": "Vorläufige Prüfung: die vollständige Prüfung läuft noch.",
    "fr": "Vérification préliminaire : la vérification complète est en cours.",
    "es": "Comprobación preliminar: la comprobación completa sigue en curso.",
}


async def run_fast(
    session: AsyncSession,
    *,
    settings: Settings,
    publishers: PublisherRegistry,
    methodology: Methodology,
    language: LanguageService,
    job: JobRow,
    text: str,
    response_language: str | None,
) -> CheckResponse:
    payload = job.payload or {}
    decision = language.resolve(text, response_language)
    instance = await get_instance(session)
    pipeline = pipeline_info(settings, publishers, methodology, instance)
    llm = LLMClient(settings, consumer="fast", request_id=job.id)
    preliminary: FactCheckResult | None = None
    try:
        hit = await cache_lookup(
            session,
            llm,
            claim=normalize_text(text),
            language=decision.response,
            corpus_version=instance.corpus_version,
            threshold=settings.cache_similarity_threshold,
            user_id=job.user_id,
        )
    except LLMError:
        logger.warning("fast_cache_unavailable")
        hit = None
    if hit is not None:
        cached, similarity = hit
        preliminary = _from_cached(
            cached,
            job=job,
            text=text,
            decision_detected=decision.detected,
            decision_response=decision.response,
            payload=payload,
            similarity=similarity,
        )
    else:
        preliminary = await _cold_preliminary(
            llm,
            job=job,
            text=text,
            detected=decision.detected,
            response=decision.response,
            payload=payload,
            methodology=methodology,
            language=language,
            pipeline=pipeline,
        )
    preliminary.pipeline = pipeline
    job.payload = {**payload, "previous_result_id": preliminary.id}
    session.add(result_to_row(preliminary, user_id=job.user_id))
    await session.flush()
    return CheckResponse(result=preliminary, compact=build_compact(preliminary))


def _input_info(*, text: str, detected: str, payload: dict[str, Any]) -> InputInfo:
    source_url = payload.get("source_url")
    source_file_name = payload.get("source_file_name")
    source_image = bool(payload.get("source_image"))
    return InputInfo(
        type="image"
        if source_image
        else ("url" if source_url else ("file" if source_file_name else "text")),
        text=text,
        language=detected,
        url=source_url,
        file_name=source_file_name,
        media_type=payload.get("source_media_type"),
        size_bytes=payload.get("source_size_bytes"),
        context={"messages": payload.get("context")} if payload.get("context") else None,
        sha256=sha256_text(text),
    )


def _preliminary_warnings(*, cold: bool, reason: str | None = None) -> list[WarningInfo]:
    warnings = [
        WarningInfo(
            code="preliminary_result",
            message="This is a preliminary result; the full check is running.",
        ),
        WarningInfo(
            code="full_result_follows",
            message="The full result will replace this version.",
        ),
    ]
    if cold and reason:
        warnings.append(WarningInfo(code="provider_fallback", message=reason))
    return warnings


def _from_cached(
    cached: Result,
    *,
    job: JobRow,
    text: str,
    decision_detected: str,
    decision_response: str,
    payload: dict[str, Any],
    similarity: float,
) -> FactCheckResult:
    base = row_to_result(cached)
    now = utcnow()
    return base.model_copy(
        update={
            "id": new_id("fc"),
            "job_id": job.id,
            "version": 1,
            "previous_version_id": None,
            "status": ResultStatus.COMPLETE,
            "preliminary": True,
            "turn_type": TurnType(payload.get("turn_type") or TurnType.NEW_CLAIM.value),
            "input": _input_info(text=text, detected=decision_detected, payload=payload),
            "detected_language": decision_detected,
            "response_language": decision_response,
            "warnings": [
                WarningInfo(
                    code="preliminary_result",
                    message=(
                        "This is a preliminary result reused from a gated check "
                        f"(similarity {similarity:.3f}); the full check is running."
                    ),
                ),
                WarningInfo(
                    code="full_result_follows",
                    message="The full result will replace this version.",
                ),
                *base.warnings,
            ],
            "created_at": now,
            "completed_at": now,
            "renderings": {},
        }
    )


async def _cold_preliminary(
    llm: LLMClient,
    *,
    job: JobRow,
    text: str,
    detected: str,
    response: str,
    payload: dict[str, Any],
    methodology: Methodology,
    language: LanguageService,
    pipeline: PipelineInfo,
) -> FactCheckResult:
    now = utcnow()
    statements: list[Statement] = []
    extraction_failed = False
    domain_tags = sorted(
        {tag for checklist in methodology.checklists.values() for tag in checklist.domain_tags}
    )
    try:
        extraction = await asyncio.wait_for(
            extract_statements(
                llm,
                text=text,
                language=detected,
                topics=list(methodology.checklists),
                domain_tags=domain_tags,
                user_id=job.user_id,
            ),
            timeout=10.0,
        )
    except (TimeoutError, LLMError):
        extraction = None
        extraction_failed = True
    if extraction is not None:
        for index, located in enumerate(extraction.statements, start=1):
            statements.append(
                Statement(
                    id=f"S{index}",
                    text=located.text,
                    span=located.span,
                    kind=located.kind,
                    checkworthy=located.checkworthy,
                    relevance=located.relevance,
                    language=detected,
                    scope=located.scope,
                    topics=located.topics,
                    domain_tags=located.domain_tags,
                )
            )
    if not statements:
        extraction_failed = True
        statements = [
            Statement(
                id="S1",
                text=text,
                span={"start": 0, "end": len(text), "text": text, "source": "input"},
                kind="fact",
                checkworthy=True,
                relevance=0.5,
                language=detected,
            )
        ]
    reason = (
        "The extractor was unavailable; the input is shown as one statement."
        if extraction_failed
        else None
    )
    return FactCheckResult(
        id=new_id("fc"),
        job_id=job.id,
        version=1,
        status=ResultStatus.COMPLETE,
        preliminary=True,
        turn_type=TurnType(payload.get("turn_type") or TurnType.NEW_CLAIM.value),
        input=_input_info(text=text, detected=detected, payload=payload),
        detected_language=detected,
        response_language=response,
        overall_verdict=None,
        overall_explanation=_PRELIMINARY_TEXT.get(response, _PRELIMINARY_TEXT["en"]),
        statements=statements,
        evidence=[],
        moderation=payload.get("moderation") or {},
        warnings=_preliminary_warnings(cold=True, reason=reason),
        pipeline=pipeline,
        created_at=now,
        completed_at=now,
    )
