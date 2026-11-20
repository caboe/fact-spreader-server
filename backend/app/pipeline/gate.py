"""Pure gate, contradiction, recency and overall-verdict functions (AGENTS.md 2).

Every rule here is deliberately independent of an LLM. The verification call proposes; this
module decides. Tests exercise these functions directly with plain data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.contracts.api import Evidence, GateInfo, WarningInfo
from app.contracts.enums import Stance, Verdict
from app.pipeline.verification import VerificationProposal
from app.services.publishers import grade_at_least


@dataclass(frozen=True)
class GateConfig:
    required: int = 1
    min_quality: str = "B"
    staleness_days: int = 1095


@dataclass(frozen=True)
class ContradictionDecision:
    supporting_evidence: list[str]
    refuting_evidence: list[str]
    scope_comparison: str


@dataclass
class GateDecision:
    verdict: Verdict
    gate: GateInfo
    warnings: list[WarningInfo] = field(default_factory=list)
    contradiction: ContradictionDecision | None = None
    supporting_evidence: list[str] = field(default_factory=list)
    refuting_evidence: list[str] = field(default_factory=list)


def gate_statement(
    proposal: VerificationProposal,
    *,
    evidence_by_id: dict[str, Evidence],
    time_scope_start: date | None,
    time_scope_end: date | None,
    config: GateConfig,
    today: date | None = None,
) -> GateDecision:
    today = today or date.today()
    links = [link for link in proposal.links if link.id in evidence_by_id]
    quality_links = [
        link
        for link in links
        if grade_at_least(evidence_by_id[link.id].provenance.source_quality, config.min_quality)
    ]
    independent_sources = _independent_count([evidence_by_id[link.id] for link in quality_links])
    gate = GateInfo(
        required=config.required,
        independent_sources=independent_sources,
        min_quality=config.min_quality,
    )
    warnings: list[WarningInfo] = []
    proposed = proposal.verdict

    if proposed is Verdict.NOT_CHECKABLE:
        return GateDecision(
            verdict=proposed,
            gate=gate,
            warnings=warnings,
            supporting_evidence=_ids_for(links, Stance.SUPPORTS),
            refuting_evidence=_ids_for(links, Stance.REFUTES),
        )

    if proposed is Verdict.INSUFFICIENT_EVIDENCE:
        # A contradiction is detected by code, not left to the model (AGENTS.md invariant 2):
        # a model that links one qualifying source as supporting and another as refuting
        # but then proposes "insufficient_evidence" has described a contradiction. Without
        # one, the proposal stands; it is never upgraded to any other verdict (D69).
        contested = _contested(
            quality_links,
            gate=gate,
            evidence_by_id=evidence_by_id,
            time_scope_start=time_scope_start,
            time_scope_end=time_scope_end,
        )
        if contested is not None:
            return contested
        return GateDecision(
            verdict=proposed,
            gate=gate,
            warnings=warnings,
            supporting_evidence=_ids_for(links, Stance.SUPPORTS),
            refuting_evidence=_ids_for(links, Stance.REFUTES),
        )

    if independent_sources < config.required:
        reason = "no_qualifying_source" if not links else "source_below_min_quality"
        return _downgrade(
            gate,
            reason,
            "The evidence did not meet the minimum-source gate.",
            supporting_evidence=_ids_for(links, Stance.SUPPORTS),
            refuting_evidence=_ids_for(links, Stance.REFUTES),
        )

    supporting = _ids_for(quality_links, Stance.SUPPORTS)
    refuting = _ids_for(quality_links, Stance.REFUTES)
    contested = _contested(
        quality_links,
        gate=gate,
        evidence_by_id=evidence_by_id,
        time_scope_start=time_scope_start,
        time_scope_end=time_scope_end,
    )
    if contested is not None:
        return contested

    if proposed is Verdict.TRUE:
        if not supporting:
            return _downgrade(
                gate,
                "no_qualifying_source",
                "No qualifying source supports the statement.",
                supporting,
                refuting,
            )
        if not proposal.audit_complete:
            return _downgrade(
                gate,
                "audit_incomplete",
                "The context audit found an open confounder.",
                supporting,
                refuting,
                warning="audit_incomplete",
            )

    if proposed is Verdict.TRUE_BUT_MISLEADING:
        if not supporting:
            return _downgrade(
                gate,
                "no_qualifying_source",
                "No qualifying source supports the core of the statement.",
                supporting,
                refuting,
            )
        if not proposal.what_is_missing:
            return _downgrade(
                gate,
                "missing_context_unsupported",
                "The misleadingness claim has no supported missing-context item.",
                supporting,
                refuting,
            )
        for item in proposal.what_is_missing:
            if not any(
                evidence_id in quality_links_by_id(quality_links) for evidence_id in item.evidence
            ):
                return _downgrade(
                    gate,
                    "missing_context_unsupported",
                    "A missing-context item has no qualifying source.",
                    supporting,
                    refuting,
                )

    if proposed is Verdict.PARTIALLY_FALSE and (not supporting or not refuting):
        return _downgrade(
            gate,
            "no_qualifying_source",
            "Partially false requires both supported and refuted material.",
            supporting,
            refuting,
        )

    if proposed is Verdict.FALSE and not refuting:
        return _downgrade(
            gate,
            "no_qualifying_source",
            "No qualifying source refutes the statement.",
            supporting,
            refuting,
        )

    verdict: Verdict = proposed
    if verdict in {Verdict.TRUE, Verdict.TRUE_BUT_MISLEADING}:
        decisive = [
            evidence_by_id[evidence_id]
            for evidence_id in supporting
            if evidence_by_id[evidence_id].provenance.publication_date is not None
        ]
        newest = max(
            (
                item.provenance.publication_date
                for item in decisive
                if item.provenance.publication_date
            ),
            default=None,
        )
        present = time_scope_end is None or time_scope_end >= today
        if (
            present
            and newest is not None
            and newest < today - timedelta(days=config.staleness_days)
        ):
            gate.downgraded = True
            gate.reason = "stale_evidence"
            warnings.append(
                WarningInfo(
                    code="stale_evidence",
                    message="All decisive sources are older than the topic's staleness threshold.",
                )
            )
            verdict = Verdict.INSUFFICIENT_EVIDENCE

    return GateDecision(
        verdict=verdict,
        gate=gate,
        warnings=[*warnings, *proposal_warnings(proposal)],
        supporting_evidence=supporting,
        refuting_evidence=refuting,
    )


def overall_verdict(verdicts: list[Verdict | None]) -> Verdict:
    decided = [v for v in verdicts if v is not None and v is not Verdict.NOT_CHECKABLE]
    if not decided:
        return Verdict.NOT_CHECKABLE
    if any(v is Verdict.CONTESTED for v in decided):
        return Verdict.CONTESTED
    if all(v is Verdict.INSUFFICIENT_EVIDENCE for v in decided):
        return Verdict.INSUFFICIENT_EVIDENCE
    accurate = {Verdict.TRUE, Verdict.TRUE_BUT_MISLEADING, Verdict.PARTIALLY_FALSE}
    if any(v is Verdict.FALSE for v in decided) and not any(v in accurate for v in decided):
        return Verdict.FALSE
    if any(v in {Verdict.FALSE, Verdict.PARTIALLY_FALSE} for v in decided) and any(
        v in accurate for v in decided
    ):
        return Verdict.PARTIALLY_FALSE
    if any(v is Verdict.TRUE_BUT_MISLEADING for v in decided):
        return Verdict.TRUE_BUT_MISLEADING
    return Verdict.TRUE


def proposal_warnings(proposal: VerificationProposal) -> list[WarningInfo]:
    if proposal.audit_complete:
        return []
    return [
        WarningInfo(
            code="audit_incomplete",
            message="The context audit could not be completed from the approved corpus.",
        )
    ]


def _ids_for(links: Sequence[object], stance: Stance) -> list[str]:
    result: list[str] = []
    for link in links:
        link_stance = getattr(link, "stance", None)
        link_id = getattr(link, "id", None)
        if link_stance == stance and isinstance(link_id, str):
            result.append(link_id)
    return result


def quality_links_by_id(links: Sequence[object]) -> set[str]:
    return {str(link_id) for link in links if (link_id := getattr(link, "id", None)) is not None}


def _independent_count(evidence: list[Evidence]) -> int:
    keys: set[str] = set()
    datasets: set[str] = set()
    for item in evidence:
        dataset = item.provenance.dataset_id
        if dataset:
            if dataset in datasets:
                continue
            datasets.add(dataset)
        keys.add(item.independence_key)
    return len(keys)


def _downgrade(
    gate: GateInfo,
    reason: str,
    message: str,
    supporting_evidence: list[str],
    refuting_evidence: list[str],
    *,
    warning: str = "gate_downgraded",
) -> GateDecision:
    gate.downgraded = True
    gate.reason = reason
    return GateDecision(
        verdict=Verdict.INSUFFICIENT_EVIDENCE,
        gate=gate,
        warnings=[WarningInfo(code=warning, message=message)],
        supporting_evidence=supporting_evidence,
        refuting_evidence=refuting_evidence,
    )


def _contested(
    quality_links: Sequence[object],
    *,
    gate: GateInfo,
    evidence_by_id: dict[str, Evidence],
    time_scope_start: date | None,
    time_scope_end: date | None,
) -> GateDecision | None:
    """``contested`` when qualifying sources support and refute the same period, else None."""
    supporting = _ids_for(quality_links, Stance.SUPPORTS)
    refuting = _ids_for(quality_links, Stance.REFUTES)
    contradiction = _contradiction(
        supporting,
        refuting,
        evidence_by_id=evidence_by_id,
        time_scope_start=time_scope_start,
        time_scope_end=time_scope_end,
    )
    if contradiction is None or not _both_sides_qualify(
        contradiction, evidence_by_id=evidence_by_id
    ):
        return None
    gate.independent_sources = max(
        gate.independent_sources,
        _independent_count([evidence_by_id[eid] for eid in {*supporting, *refuting}]),
    )
    return GateDecision(
        verdict=Verdict.CONTESTED,
        gate=gate,
        warnings=[],
        contradiction=contradiction,
        supporting_evidence=contradiction.supporting_evidence,
        refuting_evidence=contradiction.refuting_evidence,
    )


def _contradiction(
    supporting: list[str],
    refuting: list[str],
    *,
    evidence_by_id: dict[str, Evidence],
    time_scope_start: date | None,
    time_scope_end: date | None,
) -> ContradictionDecision | None:
    if not supporting or not refuting:
        return None
    # A single document cannot contradict itself for this purpose; it is mixed.
    support_docs = {evidence_by_id[eid].independence_key for eid in supporting}
    refute_docs = {evidence_by_id[eid].independence_key for eid in refuting}
    if support_docs == refute_docs:
        return None
    if time_scope_start is not None or time_scope_end is not None:
        support_in_scope = [
            eid
            for eid in supporting
            if _in_scope(evidence_by_id[eid], time_scope_start, time_scope_end)
        ]
        refute_in_scope = [
            eid
            for eid in refuting
            if _in_scope(evidence_by_id[eid], time_scope_start, time_scope_end)
        ]
        if support_in_scope and refute_in_scope:
            return ContradictionDecision(supporting, refuting, "same_period")
        if support_in_scope or refute_in_scope:
            return None
    return ContradictionDecision(supporting, refuting, "same_period")


def _both_sides_qualify(
    contradiction: ContradictionDecision, *, evidence_by_id: dict[str, Evidence]
) -> bool:
    return all(eid in evidence_by_id for eid in contradiction.supporting_evidence) and all(
        eid in evidence_by_id for eid in contradiction.refuting_evidence
    )


def _in_scope(item: Evidence, start: date | None, end: date | None) -> bool:
    published = item.provenance.publication_date
    if published is None:
        return True
    if start is not None and published < start:
        return False
    return not (end is not None and published > end)
