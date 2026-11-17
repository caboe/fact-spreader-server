"""Deterministic compact report for the browser extension (PROTOCOL §3.8)."""

from __future__ import annotations

from app.contracts.api import CompactReport, FactCheckResult, KeyEvidence
from app.services.templates import confounder_label, verdict_label


def build_compact(result: FactCheckResult) -> CompactReport:
    missing: list[str] = []
    for statement in result.statements:
        for item in statement.what_is_missing:
            label = (
                confounder_label(item.confounder, result.response_language)
                if item.confounder
                else item.text
            )
            if label not in missing:
                missing.append(label)
    if not missing:
        for statement in result.statements:
            for statement_item in statement.what_is_unverifiable[:1]:
                if statement_item.text not in missing:
                    missing.append(statement_item.text)
    evidence_by_id = {item.id: item for item in result.evidence}
    key_evidence: list[KeyEvidence] = []
    for citation in _cited_ids(result):
        evidence_item = evidence_by_id.get(citation)
        if evidence_item is None:
            continue
        provenance = evidence_item.provenance
        key_evidence.append(
            KeyEvidence(
                citation=citation,
                publisher=provenance.publisher,
                publication_date=provenance.publication_date,
                url=provenance.url,
            )
        )
        if len(key_evidence) >= 3:
            break
    verdict = result.overall_verdict
    return CompactReport(
        result_id=result.id,
        version=result.version,
        preliminary=result.preliminary,
        verdict=verdict,
        verdict_label=verdict_label(verdict, result.response_language) if verdict else "",
        bottom_line=result.overall_explanation or "",
        missing_contexts=missing[:3],
        key_evidence=key_evidence,
        report_url=f"/reports/{result.id}",
        language=result.response_language,
        warnings=result.warnings,
    )


def _cited_ids(result: FactCheckResult) -> list[str]:
    seen: list[str] = []
    for statement in result.statements:
        for link in statement.evidence_links:
            if link.evidence_id not in seen:
                seen.append(link.evidence_id)
        for evidence_items in (statement.what_is_true, statement.what_is_missing):
            for evidence_item in evidence_items:
                for evidence_id in evidence_item.evidence:
                    if evidence_id not in seen:
                        seen.append(evidence_id)
    return seen
