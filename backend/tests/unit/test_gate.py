"""Gate, contradiction, recency and overall-verdict guarantees (AGENTS.md invariant 2)."""

from __future__ import annotations

from datetime import date

from app.contracts.api import Evidence, Provenance, SourceQualityBasis
from app.contracts.enums import Verdict
from app.pipeline.gate import GateConfig, gate_statement, overall_verdict
from app.pipeline.verification import VerificationProposal, _EvidenceLinkOut, _MissingOut


def make_evidence(
    evidence_id: str,
    *,
    quality: str = "A",
    published: date | None = date(2024, 1, 1),
    dataset: str | None = None,
    key: str | None = None,
) -> Evidence:
    return Evidence(
        id=evidence_id,
        evidence_id=f"psg_{evidence_id}",
        passage=f"Passage for {evidence_id}",
        passage_language="en",
        passage_hash=f"sha256:{evidence_id}",
        evidence_tier=1,
        relevance=0.9,
        independence_key=key or f"doi:{evidence_id}",
        provenance=Provenance(
            document_id=f"doc_{evidence_id}",
            document_version=1,
            title=f"Document {evidence_id}",
            publisher="Test Publisher",
            publication_date=published,
            dataset_id=dataset,
            source_quality=quality,
            source_quality_basis=SourceQualityBasis(source="shipped_list"),
            language="en",
            origin_instance_id="inst_test",
            origin_document_id=f"doc_{evidence_id}",
        ),
    )


def proposal(
    verdict: Verdict,
    *,
    links: list[tuple[str, str]] | None = None,
    missing: list[tuple[str, list[str]]] | None = None,
    audit_complete: bool = True,
) -> VerificationProposal:
    return VerificationProposal(
        verdict=verdict,
        rationale="test",
        links=[
            _EvidenceLinkOut(id=eid, stance=stance, relevance=0.9, addresses_confounders=[])
            for eid, stance in (links or [])
        ],
        what_is_true=[],
        what_is_missing=[
            _MissingOut(text=text, confounder="age", evidence=evidence_ids)
            for text, evidence_ids in (missing or [])
        ],
        what_is_unverifiable=[],
        argument_issues=[],
        audit_complete=audit_complete,
    )


def test_true_with_qualifying_source_and_complete_audit_stays_true() -> None:
    evidence = {"E1": make_evidence("E1")}
    decision = gate_statement(
        proposal(Verdict.TRUE, links=[("E1", "supports")]),
        evidence_by_id=evidence,
        time_scope_start=None,
        time_scope_end=None,
        config=GateConfig(),
    )
    assert decision.verdict is Verdict.TRUE
    assert decision.gate.independent_sources == 1
    assert not decision.gate.downgraded


def test_true_with_open_audit_is_downgraded_to_insufficient() -> None:
    evidence = {"E1": make_evidence("E1")}
    decision = gate_statement(
        proposal(Verdict.TRUE, links=[("E1", "supports")], audit_complete=False),
        evidence_by_id=evidence,
        time_scope_start=None,
        time_scope_end=None,
        config=GateConfig(),
    )
    assert decision.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert decision.gate.reason == "audit_incomplete"
    assert any(w.code == "audit_incomplete" for w in decision.warnings)


def test_true_but_misleading_needs_supported_missing_context() -> None:
    evidence = {"E1": make_evidence("E1")}
    good = gate_statement(
        proposal(
            Verdict.TRUE_BUT_MISLEADING,
            links=[("E1", "supports")],
            missing=[("Age structure is omitted.", ["E1"])],
        ),
        evidence_by_id=evidence,
        time_scope_start=None,
        time_scope_end=None,
        config=GateConfig(),
    )
    assert good.verdict is Verdict.TRUE_BUT_MISLEADING
    bad = gate_statement(
        proposal(
            Verdict.TRUE_BUT_MISLEADING,
            links=[("E1", "supports")],
            missing=[("No source for this.", ["E2"])],
        ),
        evidence_by_id=evidence,
        time_scope_start=None,
        time_scope_end=None,
        config=GateConfig(),
    )
    assert bad.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert bad.gate.reason == "missing_context_unsupported"


def test_d_grade_source_does_not_satisfy_the_gate() -> None:
    evidence = {"E1": make_evidence("E1", quality="D")}
    decision = gate_statement(
        proposal(Verdict.TRUE, links=[("E1", "supports")]),
        evidence_by_id=evidence,
        time_scope_start=None,
        time_scope_end=None,
        config=GateConfig(),
    )
    assert decision.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert decision.gate.reason == "source_below_min_quality"


def test_same_period_support_and_refutation_is_contested() -> None:
    evidence = {
        "E1": make_evidence("E1", published=date(2024, 1, 1)),
        "E2": make_evidence("E2", published=date(2024, 2, 1)),
    }
    decision = gate_statement(
        proposal(
            Verdict.TRUE,
            links=[("E1", "supports"), ("E2", "refutes")],
        ),
        evidence_by_id=evidence,
        time_scope_start=date(2023, 1, 1),
        time_scope_end=date(2024, 12, 31),
        config=GateConfig(),
    )
    assert decision.verdict is Verdict.CONTESTED
    assert decision.contradiction is not None
    assert decision.contradiction.supporting_evidence == ["E1"]
    assert decision.contradiction.refuting_evidence == ["E2"]


def test_an_insufficient_proposal_with_a_same_period_contradiction_is_contested() -> None:
    """Prevents the model from deciding away a contradiction (AGENTS.md invariant 2, D69).

    In the evaluation the verifier linked the 5,200 source as supporting and the 3,900
    source as refuting, then proposed insufficient_evidence; the gate returned that
    proposal before contradiction detection ran, so claim-044 lost `contested`.
    """
    evidence = {
        "E1": make_evidence("E1", published=date(2024, 1, 1)),
        "E2": make_evidence("E2", published=date(2024, 2, 1)),
        "E3": make_evidence("E3", published=date(2024, 3, 1)),
    }
    decision = gate_statement(
        proposal(
            Verdict.INSUFFICIENT_EVIDENCE,
            links=[("E1", "supports"), ("E2", "refutes"), ("E3", "context")],
            audit_complete=False,
        ),
        evidence_by_id=evidence,
        time_scope_start=date(2024, 1, 1),
        time_scope_end=date(2024, 12, 31),
        config=GateConfig(),
    )
    assert decision.verdict is Verdict.CONTESTED
    assert decision.contradiction is not None
    assert decision.contradiction.supporting_evidence == ["E1"]
    assert decision.contradiction.refuting_evidence == ["E2"]
    assert decision.gate.independent_sources == 3


def test_an_insufficient_proposal_without_a_qualifying_contradiction_stays_insufficient() -> None:
    """The rule only detects contradictions; it never upgrades to any other verdict."""
    cases = [
        # One side only.
        ({"E1": make_evidence("E1")}, [("E1", "supports")]),
        # The refuting source is below the minimum quality.
        (
            {"E1": make_evidence("E1"), "E2": make_evidence("E2", quality="D")},
            [("E1", "supports"), ("E2", "refutes")],
        ),
        # Both stances from the same document are mixed, not a contradiction.
        (
            {"E1": make_evidence("E1", key="doi:same"), "E2": make_evidence("E2", key="doi:same")},
            [("E1", "supports"), ("E2", "refutes")],
        ),
        # Only context links.
        ({"E1": make_evidence("E1")}, [("E1", "context")]),
    ]
    for evidence, links in cases:
        decision = gate_statement(
            proposal(Verdict.INSUFFICIENT_EVIDENCE, links=links),
            evidence_by_id=evidence,
            time_scope_start=None,
            time_scope_end=None,
            config=GateConfig(),
        )
        assert decision.verdict is Verdict.INSUFFICIENT_EVIDENCE, links
        assert decision.contradiction is None


def test_a_not_checkable_proposal_is_never_contested() -> None:
    evidence = {"E1": make_evidence("E1"), "E2": make_evidence("E2")}
    decision = gate_statement(
        proposal(Verdict.NOT_CHECKABLE, links=[("E1", "supports"), ("E2", "refutes")]),
        evidence_by_id=evidence,
        time_scope_start=None,
        time_scope_end=None,
        config=GateConfig(),
    )
    assert decision.verdict is Verdict.NOT_CHECKABLE


def test_out_of_scope_refutation_is_a_development_not_a_contradiction() -> None:
    evidence = {
        "E1": make_evidence("E1", published=date(2024, 1, 1)),
        "E2": make_evidence("E2", published=date(2019, 1, 1)),
    }
    decision = gate_statement(
        proposal(
            Verdict.TRUE,
            links=[("E1", "supports"), ("E2", "refutes")],
        ),
        evidence_by_id=evidence,
        time_scope_start=date(2023, 1, 1),
        time_scope_end=date(2024, 12, 31),
        config=GateConfig(),
    )
    assert decision.verdict is Verdict.TRUE
    assert decision.contradiction is None


def test_stale_source_caps_a_present_tense_true() -> None:
    evidence = {"E1": make_evidence("E1", published=date(2018, 1, 1))}
    decision = gate_statement(
        proposal(Verdict.TRUE, links=[("E1", "supports")]),
        evidence_by_id=evidence,
        time_scope_start=None,
        time_scope_end=None,
        config=GateConfig(staleness_days=1095),
        today=date(2026, 11, 16),
    )
    assert decision.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert decision.gate.reason == "stale_evidence"


def test_stale_source_does_not_cap_a_past_scoped_claim() -> None:
    evidence = {"E1": make_evidence("E1", published=date(2018, 1, 1))}
    decision = gate_statement(
        proposal(Verdict.TRUE, links=[("E1", "supports")]),
        evidence_by_id=evidence,
        time_scope_start=date(2017, 1, 1),
        time_scope_end=date(2018, 12, 31),
        config=GateConfig(staleness_days=1095),
        today=date(2026, 11, 16),
    )
    assert decision.verdict is Verdict.TRUE


def test_shared_dataset_counts_once_for_independence() -> None:
    evidence = {
        "E1": make_evidence("E1", dataset="same", key="doi:a"),
        "E2": make_evidence("E2", dataset="same", key="doi:b"),
    }
    decision = gate_statement(
        proposal(
            Verdict.TRUE_BUT_MISLEADING,
            links=[("E1", "supports"), ("E2", "context")],
            missing=[("Context.", ["E1"])],
        ),
        evidence_by_id=evidence,
        time_scope_start=None,
        time_scope_end=None,
        config=GateConfig(required=2),
    )
    assert decision.verdict is Verdict.INSUFFICIENT_EVIDENCE
    assert decision.gate.reason == "source_below_min_quality"


def test_overall_verdict_priorities() -> None:
    assert overall_verdict([Verdict.NOT_CHECKABLE, None]) is Verdict.NOT_CHECKABLE
    assert (
        overall_verdict([Verdict.INSUFFICIENT_EVIDENCE, Verdict.INSUFFICIENT_EVIDENCE])
        is Verdict.INSUFFICIENT_EVIDENCE
    )
    assert overall_verdict([Verdict.CONTESTED, Verdict.FALSE]) is Verdict.CONTESTED
    assert overall_verdict([Verdict.FALSE, Verdict.INSUFFICIENT_EVIDENCE]) is Verdict.FALSE
    assert overall_verdict([Verdict.FALSE, Verdict.TRUE]) is Verdict.PARTIALLY_FALSE
    assert (
        overall_verdict([Verdict.TRUE_BUT_MISLEADING, Verdict.TRUE]) is Verdict.TRUE_BUT_MISLEADING
    )
    assert overall_verdict([Verdict.TRUE, Verdict.INSUFFICIENT_EVIDENCE]) is Verdict.TRUE
