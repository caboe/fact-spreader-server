"""Local publisher overrides are merged, capped and diffed (IMPLEMENT Phase 6)."""

from __future__ import annotations

import pytest
from app.core.errors import AppError
from app.services.publisher_overrides import (
    diff,
    effective_registry,
    validate_overrides,
)
from app.services.publishers import PublisherRegistry

BASE = PublisherRegistry(
    version="2026-11-16",
    entries=[
        {
            "key": "bka",
            "publisher": "Federal Criminal Police Office (BKA)",
            "aliases": ["BKA"],
            "grade": "A",
            "match": {"domains": ["bka.de"]},
        },
        {"key": "blog", "publisher": "Example Blog", "grade": "B", "match": {}},
    ],
)


def test_an_override_changes_the_effective_grade_and_names_the_local_list() -> None:
    effective = effective_registry(BASE, [{"key": "bka", "grade": "D"}])
    match = effective.resolve(publisher="BKA")
    assert match.grade == "D"
    assert match.basis.source == "local_list"
    assert match.basis.list_version == effective.version
    assert effective.version.startswith("2026-11-16+local:")
    assert effective.resolve(publisher=None, url="https://www.bka.de/report").grade == "D"


def test_a_disputed_override_is_capped_at_c() -> None:
    effective = effective_registry(BASE, [{"key": "blog", "grade": "A", "disputed": True}])
    assert effective.resolve(publisher="Example Blog").grade == "C"


def test_the_diff_shows_the_shipped_and_local_values() -> None:
    changes = diff(BASE, [{"key": "bka", "grade": "D", "disputed": True}])
    assert {
        (change["key"], change["field"], change["shipped"], change["local"]) for change in changes
    } == {
        ("bka", "grade", "A", "D"),
        ("bka", "disputed", None, True),
    }


def test_an_unknown_or_duplicate_key_is_rejected() -> None:
    with pytest.raises(AppError) as unknown:
        validate_overrides(BASE, [{"key": "not-in-list", "grade": "A"}])
    assert unknown.value.code == "unknown_publisher_key"
    with pytest.raises(AppError) as duplicate:
        validate_overrides(BASE, [{"key": "bka", "grade": "B"}, {"key": "bka", "grade": "C"}])
    assert duplicate.value.code == "duplicate_publisher_key"
    with pytest.raises(AppError) as grade:
        validate_overrides(BASE, [{"key": "bka", "grade": "F"}])
    assert grade.value.code == "invalid_grade"
