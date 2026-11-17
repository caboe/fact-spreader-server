"""Persona rendering and consistency fallbacks (PERSONAS.md, invariant 3)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from app.contracts.api import (
    ArgumentIssue,
    Evidence,
    EvidenceLink,
    FactCheckResult,
    InputInfo,
    ModerationInfo,
    PipelineInfo,
    Provenance,
    Scope,
    SourceQualityBasis,
    Span,
    Statement,
    WhatIsMissing,
    WhatIsTrue,
)
from app.contracts.enums import StatementKind, Verdict
from app.rendering import RenderingService
from app.services.moderation import ModerationService
from app.services.personas import PersonaRegistry

from tests.fakes import FakeLLM

ROOT = Path(__file__).resolve().parents[3]


def _result() -> FactCheckResult:
    evidence = Evidence(
        id="E1",
        evidence_id="psg_test",
        passage="Registered suspects are overrepresented in the raw table.",
        passage_language="en",
        passage_hash="sha256:test",
        evidence_tier=1,
        relevance=0.9,
        independence_key="doi:test",
        provenance=Provenance(
            document_id="doc_test",
            document_version=1,
            title="Fixture",
            publisher="BKA",
            source_quality="A",
            source_quality_basis=SourceQualityBasis(source="shipped_list", entry="bka"),
            language="en",
            origin_instance_id="inst_test",
            origin_document_id="doc_test",
        ),
    )
    statement = Statement(
        id="S1",
        text="Immigrants commit more crimes.",
        span=Span(start=0, end=30, text="Immigrants commit more crimes."),
        kind=StatementKind.FACT,
        checkworthy=True,
        scope=Scope(),
        verdict=Verdict.TRUE_BUT_MISLEADING,
        evidence_links=[EvidenceLink(evidence_id="E1", stance="supports")],
        what_is_true=[WhatIsTrue(text="The raw figure is higher.", evidence=["E1"])],
        what_is_missing=[
            WhatIsMissing(text="Age is not adjusted.", confounder="age", evidence=["E1"])
        ],
    )
    return FactCheckResult(
        id="fc_test",
        job_id="job_test",
        status="complete",
        input=InputInfo(type="text", text="Immigrants commit more crimes.", language="en"),
        detected_language="en",
        response_language="en",
        overall_verdict=Verdict.TRUE_BUT_MISLEADING,
        overall_explanation="The core is supported, but essential context is missing.",
        statements=[statement],
        evidence=[evidence],
        argument_issues=[
            ArgumentIssue(
                pattern="omitted_confounders",
                statement_ids=["S1"],
                explanation="The raw association omits age structure.",
                evidence=["E1"],
            )
        ],
        moderation=ModerationInfo(),
        pipeline=PipelineInfo(
            corpus_version="sha256:test",
            config_hash="sha256:test",
        ),
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


def service(fake: FakeLLM) -> RenderingService:
    return RenderingService(
        llm=fake,
        personas=PersonaRegistry.from_path(ROOT / "PERSONAS.md"),
        moderation=ModerationService(fake),
    )


@pytest.mark.asyncio
async def test_a_valid_persona_narrative_is_released() -> None:
    fake = FakeLLM(
        narratives=[
            "Verdict: True, but misleading. The raw figure is supported [E1]; "
            "age context is missing [E1]."
        ]
    )
    outcome = await service(fake).render(_result(), persona_id="analyst", language="en")
    assert outcome.rendering.consistency.passed is True
    assert outcome.rendering.format == "persona"
    assert "[E1]" in outcome.rendering.text
    assert not outcome.warnings


@pytest.mark.asyncio
async def test_an_invalid_citation_falls_back_to_the_template() -> None:
    fake = FakeLLM(narratives=["A claim with an invented source [E99].", "Still [E99]."])
    outcome = await service(fake).render(_result(), persona_id="analyst", language="en")
    assert outcome.rendering.consistency.fallback is True
    assert outcome.rendering.format == "template"
    assert any(w.code == "consistency_fallback" for w in outcome.warnings)
    assert "[E99]" not in outcome.rendering.text


@pytest.mark.asyncio
async def test_impersonal_persona_rejects_second_person_renderings() -> None:
    fake = FakeLLM(narratives=["You are wrong [E1].", "You are still wrong [E1]."])
    outcome = await service(fake).render(_result(), persona_id="analyst", language="en")
    assert outcome.rendering.consistency.fallback is True


@pytest.mark.asyncio
async def test_output_moderation_replaces_the_narrative() -> None:
    fake = FakeLLM(narratives=["A perfectly cited narrative [E1]."], block=True)
    outcome = await service(fake).render(_result(), persona_id="mediator", language="en")
    assert outcome.rendering.format == "template"
    assert outcome.output_moderation is not None
    assert any(w.code == "output_moderation_replaced" for w in outcome.warnings)


@pytest.mark.asyncio
async def test_unavailable_renderer_uses_the_template_not_silence() -> None:
    fake = FakeLLM(unavailable=True)
    outcome = await service(fake).render(_result(), persona_id="analyst", language="en")
    assert outcome.rendering.consistency.fallback is True
    assert outcome.rendering.text
