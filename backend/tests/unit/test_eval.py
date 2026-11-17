"""The evaluation runner refuses to measure an unusable set (IMPLEMENT Phase 9)."""

from __future__ import annotations

from pathlib import Path

import pytest
from app.tools.eval import REQUIRED_FLAGS, VERDICTS, check_coverage, load_cases, score


def _case(case_id: str, verdict: str, flags: list[str] | None = None) -> str:
    import json

    return json.dumps(
        {
            "id": case_id,
            "text": f"claim {case_id}",
            "expected_verdict": verdict,
            "flags": flags or [],
        }
    )


def _write(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "set.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_a_complete_set_passes_coverage(tmp_path: Path) -> None:
    lines = [_case(f"c{i}", verdict) for i, verdict in enumerate(VERDICTS)]
    lines += [_case(f"flag-{flag}", "true", [flag]) for flag in REQUIRED_FLAGS]
    lines += [_case(f"extra-{i}", "true") for i in range(40)]
    coverage = check_coverage(load_cases(_write(tmp_path, lines)))
    assert coverage["cases"] == len(lines)
    assert coverage["verdict_counts"]["contested"] == 1


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    lines = [_case(f"c{i}", verdict) for i, verdict in enumerate(VERDICTS)]
    lines += [_case("duplicate", "true")]
    lines += [_case("duplicate", "false")]
    with pytest.raises(SystemExit):
        check_coverage(load_cases(_write(tmp_path, lines)))


def test_a_missing_verdict_is_rejected(tmp_path: Path) -> None:
    lines = [
        _case(f"c{i}", verdict) for i, verdict in enumerate(VERDICTS) if verdict != "contested"
    ]
    lines += [_case(f"extra-{i}", "true") for i in range(42)]
    with pytest.raises(SystemExit):
        check_coverage(load_cases(_write(tmp_path, lines)))


def test_metrics_report_per_class_and_macro_f1() -> None:
    from app.tools.eval import Case

    cases = [
        Case(id=f"c{i}", text="", expected=verdict, flags=frozenset())
        for i, verdict in enumerate(VERDICTS)
    ]
    predictions = {
        f"c{i}": {"id": f"c{i}", "predicted_verdict": verdict, "latency_ms": 1000}
        for i, verdict in enumerate(VERDICTS)
    }
    metrics = score(cases, predictions)
    assert metrics["accuracy"] == 1.0
    assert metrics["macro_f1"] == 1.0
    assert metrics["misleadingness_recall"] == 1.0
    assert metrics["cache_hit_rate"] == 1.0


def test_a_missing_prediction_fails_instead_of_scoring_silently() -> None:
    from app.tools.eval import Case

    cases = [Case(id="c1", text="", expected="true", flags=frozenset())]
    with pytest.raises(SystemExit):
        score(cases, {})
