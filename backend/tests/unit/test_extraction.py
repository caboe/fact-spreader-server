"""Span location and overlap handling for extraction (PURPOSE §3.1)."""

from __future__ import annotations

from app.contracts.api import Scope, Span
from app.contracts.enums import StatementKind
from app.pipeline.extraction import LocatedStatement, _dedupe_overlaps, _locate


def statement(start: int, end: int, text: str) -> LocatedStatement:
    return LocatedStatement(
        text=text,
        span=Span(start=start, end=end, text=text),
        kind=StatementKind.FACT,
        checkworthy=True,
        relevance=0.5,
        scope=Scope(),
        topics=[],
        domain_tags=[],
        keywords_high=[],
        keywords_low=[],
    )


def test_exact_span_is_found() -> None:
    text = "The rate is high. It will fall."
    assert _locate(text, "The rate is high.") == (0, 17)


def test_case_and_whitespace_variants_are_located() -> None:
    text = "The  rate\nis high."
    found = _locate(text, "the rate is high.")
    assert found is not None
    assert text[found[0] : found[1]] == text


def test_unlocatable_text_is_rejected() -> None:
    assert _locate("The rate is high.", "A completely different sentence.") is None


def test_overlapping_extractions_keep_the_longer_one() -> None:
    text = "the raw figure is misleading"
    kept = _dedupe_overlaps(
        [
            statement(0, 12, text[0:12]),
            statement(0, len(text), text),
            statement(10, 20, text[10:20]),
        ]
    )
    assert len(kept) == 1
    assert kept[0].span.text == text
