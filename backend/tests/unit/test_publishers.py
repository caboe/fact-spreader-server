"""Publisher-list resolution (PURPOSE §3.1b)."""

from __future__ import annotations

from pathlib import Path

from app.services.publishers import PublisherRegistry, grade_at_least

ROOT = Path(__file__).resolve().parents[3]


def registry() -> PublisherRegistry:
    return PublisherRegistry.from_path(ROOT / "methodology" / "publishers.json")


def test_known_publisher_by_name() -> None:
    match = registry().resolve(
        publisher="Federal Criminal Police Office (BKA)",
        url="https://www.bka.de/fixture/pks",
    )
    assert match.grade == "A"
    assert match.basis.source == "shipped_list"


def test_known_publisher_by_domain_without_name() -> None:
    match = registry().resolve(publisher=None, url="https://www.destatis.de/x")
    assert match.grade == "A"


def test_doi_prefix_matches() -> None:
    match = registry().resolve(publisher="Something", doi="10.1787/abc")
    assert match.grade == "A"


def test_unknown_publisher_is_d_and_unassessed() -> None:
    match = registry().resolve(publisher="Totally Unknown Blog", url="https://example.invalid")
    assert match.grade == "D"
    assert match.basis.source == "default_unknown"


def test_grade_order() -> None:
    assert grade_at_least("A", "B")
    assert grade_at_least("B", "B")
    assert not grade_at_least("C", "B")
    assert not grade_at_least("D", "C")
