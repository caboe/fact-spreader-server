"""Deterministic translated substance labels (PURPOSE §3.9, invariant 3)."""

from __future__ import annotations

from app.contracts.enums import Verdict
from app.services.templates import (
    confounder_label,
    fallback_warning,
    gate_fallback_text,
    no_matching_rationale,
    overall_explanation,
    refusal_text,
    unsupported_language_notice,
    verdict_label,
)


def test_every_verdict_has_a_label_in_the_four_languages() -> None:
    for language in ("en", "de", "fr", "es"):
        for verdict in Verdict:
            label = verdict_label(verdict, language)
            assert label
            assert label != verdict.value


def test_overall_explanations_are_localized() -> None:
    assert overall_explanation(Verdict.CONTESTED, "de") != overall_explanation(
        Verdict.CONTESTED, "en"
    )
    assert overall_explanation(Verdict.INSUFFICIENT_EVIDENCE, "fr")


def test_refusal_and_notice_are_localized() -> None:
    assert "minor" in refusal_text("en").lower()
    assert "Minderjährigen" in refusal_text("de")
    assert "anglais" in unsupported_language_notice("fr")


def test_confounder_labels_have_a_graceful_fallback() -> None:
    assert confounder_label("age", "de") == "Altersstruktur"
    assert confounder_label("not_a_confounder", "en") == "not a confounder"


def test_fallback_warnings_are_localized() -> None:
    assert "deterministischen" in fallback_warning("consistency_fallback", "de")
    assert "Output moderation" in fallback_warning("output_moderation_replaced", "en")
    assert fallback_warning("unknown_warning", "de") == "unknown_warning"


def test_deterministic_analysis_fallbacks_are_localized() -> None:
    assert "Kein freigegebener" in no_matching_rationale("de")
    assert "Quelle" in gate_fallback_text("de")
    assert "Aucun passage" in no_matching_rationale("fr")
