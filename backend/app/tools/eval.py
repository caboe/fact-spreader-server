"""Labelled evaluation runner (IMPLEMENT Phase 9).

The set is the measurement: this tool refuses to score a set with duplicate ids, missing
verdict classes or missing required flags, and it refuses to score an empty or incomplete
prediction file. ``--live`` asks the running stack for real checks and records predictions;
offline mode replays those predictions without a network or a model call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

import httpx

VERDICTS = (
    "true",
    "true_but_misleading",
    "partially_false",
    "false",
    "contested",
    "insufficient_evidence",
    "not_checkable",
)
REQUIRED_FLAGS = ("cross_lingual", "quote_context", "stale", "injection")
MIN_CASES = 24


def _fail(message: str) -> NoReturn:
    print(f"EVAL FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


@dataclass(frozen=True)
class Case:
    id: str
    text: str
    expected: str
    flags: frozenset[str]
    domain: str = ""
    note: str = ""


def load_cases(path: Path) -> list[Case]:
    if not path.exists():
        _fail(f"the labelled set {path} does not exist")
    cases: list[Case] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            _fail(f"line {number} is not JSON: {exc}")
        expected = str(raw.get("expected_verdict") or "")
        if expected not in VERDICTS:
            _fail(f"line {number} has unknown expected_verdict {expected!r}")
        flags = frozenset(str(flag) for flag in raw.get("flags") or [])
        unknown = flags - set(REQUIRED_FLAGS)
        if unknown:
            _fail(f"line {number} has unknown flags {sorted(unknown)}")
        cases.append(
            Case(
                id=str(raw.get("id") or ""),
                text=str(raw.get("text") or ""),
                expected=expected,
                flags=flags,
                domain=str(raw.get("domain") or ""),
                note=str(raw.get("note") or ""),
            )
        )
    if not cases:
        _fail(f"the labelled set {path} is empty")
    return cases


def check_coverage(cases: list[Case]) -> dict[str, Any]:
    ids = [case.id for case in cases]
    if not all(ids):
        _fail("every case needs an id")
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        _fail(f"duplicate ids: {duplicates[:10]}")
    if len(cases) < MIN_CASES:
        _fail(f"the set has {len(cases)} cases, fewer than the required {MIN_CASES}")
    present = {case.expected for case in cases}
    missing = [verdict for verdict in VERDICTS if verdict not in present]
    if missing:
        _fail(f"the set does not cover these verdicts: {missing}")
    flags = {flag for case in cases for flag in case.flags}
    missing_flags = [flag for flag in REQUIRED_FLAGS if flag not in flags]
    if missing_flags:
        _fail(f"the set does not cover these flags: {missing_flags}")
    return {
        "cases": len(cases),
        "verdict_counts": {
            verdict: sum(1 for c in cases if c.expected == verdict) for verdict in VERDICTS
        },
        "flags": {flag: sum(1 for c in cases if flag in c.flags) for flag in REQUIRED_FLAGS},
    }


def load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        _fail(f"the predictions file {path} does not exist; run --live first")
    predictions: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        raw = json.loads(line)
        predictions[str(raw["id"])] = raw
    if not predictions:
        _fail(f"the predictions file {path} is empty")
    return predictions


def _f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def score(cases: list[Case], predictions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    missing = [case.id for case in cases if case.id not in predictions]
    if missing:
        _fail(f"no prediction for {len(missing)} cases, first: {missing[:5]}")
    wrong_shape = [
        case.id for case in cases if predictions[case.id].get("predicted_verdict") not in VERDICTS
    ]
    if wrong_shape:
        _fail(f"a prediction has no valid verdict, first: {wrong_shape[:5]}")

    per_class: dict[str, dict[str, float | int]] = {}
    correct = 0
    for verdict in VERDICTS:
        tp = sum(
            1
            for case in cases
            if case.expected == verdict and predictions[case.id]["predicted_verdict"] == verdict
        )
        fp = sum(
            1
            for case in cases
            if case.expected != verdict and predictions[case.id]["predicted_verdict"] == verdict
        )
        fn = sum(
            1
            for case in cases
            if case.expected == verdict and predictions[case.id]["predicted_verdict"] != verdict
        )
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        per_class[verdict] = {
            "support": tp + fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(_f1(precision, recall), 4),
        }
    for case in cases:
        if predictions[case.id]["predicted_verdict"] == case.expected:
            correct += 1

    latencies = sorted(
        int(prediction["latency_ms"])
        for prediction in predictions.values()
        if isinstance(prediction.get("latency_ms"), (int, float))
    )

    def percentile(values: list[int], fraction: float) -> float | None:
        if not values:
            return None
        index = min(len(values) - 1, max(0, round(fraction * (len(values) - 1))))
        return float(values[index])

    downgraded = sum(
        1 for prediction in predictions.values() if prediction.get("gate_downgraded") is True
    )
    with_rendering = [
        prediction for prediction in predictions.values() if prediction.get("has_rendering") is True
    ]
    fallbacks = sum(
        1 for prediction in with_rendering if prediction.get("consistency_fallback") is True
    )
    cache_hits = sum(1 for latency in latencies if latency < 1500)

    macro_f1 = statistics.fmean(float(per_class[verdict]["f1"]) for verdict in VERDICTS)
    cost = sum(float(prediction.get("cost_usd") or 0.0) for prediction in predictions.values())
    return {
        "cases": len(cases),
        "accuracy": round(correct / len(cases), 4),
        "macro_f1": round(macro_f1, 4),
        "misleadingness_recall": per_class["true_but_misleading"]["recall"],
        "per_class": per_class,
        "gate_downgrade_rate": round(downgraded / len(predictions), 4),
        "consistency_fallback_rate": (
            round(fallbacks / len(with_rendering), 4) if with_rendering else None
        ),
        "latency_p50_ms": percentile(latencies, 0.5),
        "latency_p95_ms": percentile(latencies, 0.95),
        "cache_hit_rate": round(cache_hits / len(latencies), 4) if latencies else None,
        "cost_usd": round(cost, 6),
        "cost_per_check_usd": round(cost / len(predictions), 6),
    }


async def _usage_cost(client: httpx.AsyncClient, headers: dict[str, str]) -> float:
    response = await client.get("/v1/usage/summary", headers=headers)
    if response.status_code == 200:
        return float(response.json().get("totals", {}).get("cost_usd") or 0.0)
    return 0.0


async def _poll(
    client: httpx.AsyncClient, job_id: str, headers: dict[str, str], budget_seconds: float
) -> dict[str, Any]:
    deadline = time.monotonic() + budget_seconds
    while time.monotonic() < deadline:
        response = await client.get(f"/v1/factcheck/{job_id}", headers=headers)
        if response.status_code not in {200, 202}:
            _fail(f"polling {job_id} returned HTTP {response.status_code}: {response.text[:200]}")
        payload: dict[str, Any] = response.json()
        state = (payload.get("job") or {}).get("state")
        if state in {"failed", "cancelled"}:
            _fail(f"job {job_id} ended as {state}: {(payload.get('job') or {}).get('error')}")
        if payload.get("result") is not None:
            return payload
        await asyncio.sleep(1.5)
    _fail(f"job {job_id} did not finish within {budget_seconds}s")


async def _one_case(
    client: httpx.AsyncClient,
    case: Case,
    *,
    headers: dict[str, str],
    fast: bool,
    budget_seconds: float,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        started_case = time.perf_counter()
        for attempt in range(3):
            response = await client.post(
                "/v1/factcheck",
                headers=headers,
                json={
                    "input": {"type": "text", "text": case.text},
                    "fast": fast,
                    "mode": "async",
                },
            )
            if response.status_code not in {429, 502, 503, 504}:
                break
            wait = 5 * (attempt + 1)
            print(f"  {case.id}: transient HTTP {response.status_code}, retry in {wait}s")
            await asyncio.sleep(wait)
        if response.status_code == 200:
            check = response.json()
            job_id = (check.get("job") or {}).get("id", "")
        elif response.status_code == 202:
            job_id = response.json()["job"]["id"]
            envelope = await _poll(client, job_id, headers, budget_seconds)
            check = envelope["result"]
        else:
            _fail(
                f"POST /v1/factcheck for {case.id} returned HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        latency_ms = int((time.perf_counter() - started_case) * 1000)
        result = check.get("result") or {}
        rendering = check.get("rendering") or {}
        consistency = rendering.get("consistency") or {}
        statements = result.get("statements") or []
        print(f"  {case.id}: {result.get('overall_verdict')} in {latency_ms} ms")
        return {
            "id": case.id,
            "expected_verdict": case.expected,
            "predicted_verdict": result.get("overall_verdict"),
            "result_id": result.get("id"),
            "job_id": job_id,
            "preliminary": bool(result.get("preliminary")),
            "latency_ms": latency_ms,
            "gate_downgraded": any(
                bool((statement.get("gate") or {}).get("downgraded")) for statement in statements
            ),
            "has_rendering": bool(rendering),
            "consistency_fallback": bool(consistency.get("fallback")),
            "recorded_at": datetime.now(UTC).isoformat(),
            "cost_usd": 0.0,
        }


async def _run_live_async(
    cases: list[Case],
    *,
    base_url: str,
    api_key: str,
    fast: bool,
    limit: int,
    budget_seconds: float,
    out: Path,
    concurrency: int,
) -> dict[str, dict[str, Any]]:
    headers = {"Authorization": f"Bearer {api_key}"}
    selected = cases[:limit] if limit else cases
    started = datetime.now(UTC)
    semaphore = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(base_url=base_url, timeout=30.0) as client:
        before = await _usage_cost(client, headers)
        results = await asyncio.gather(
            *(
                _one_case(
                    client,
                    case,
                    headers=headers,
                    fast=fast,
                    budget_seconds=budget_seconds,
                    semaphore=semaphore,
                )
                for case in selected
            )
        )
        after = await _usage_cost(client, headers)
    predictions = {prediction["id"]: prediction for prediction in results}
    delta = max(0.0, after - before)
    share = round(delta / len(predictions), 6) if predictions else 0.0
    for prediction in predictions.values():
        prediction["cost_usd"] = share
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        handle.write(
            f"# Recorded evaluation predictions from {started.isoformat()} (fast={fast}).\n"
        )
        handle.write("# Replay offline with: make eval-recorded\n")
        for prediction in predictions.values():
            handle.write(json.dumps(prediction, ensure_ascii=False) + "\n")
    print(f"recorded {len(predictions)} predictions to {out}")
    return predictions


def run_live(
    cases: list[Case],
    *,
    base_url: str,
    api_key: str,
    fast: bool,
    limit: int,
    budget_seconds: float,
    out: Path,
    concurrency: int = 4,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = asyncio.run(
        _run_live_async(
            cases,
            base_url=base_url,
            api_key=api_key,
            fast=fast,
            limit=limit,
            budget_seconds=budget_seconds,
            out=out,
            concurrency=concurrency,
        )
    )
    return result


def _print_report(metrics: dict[str, Any], coverage: dict[str, Any]) -> None:
    print("\nCoverage")
    print(f"  cases: {coverage['cases']}")
    print(
        "  verdicts: "
        + ", ".join(f"{key}={value}" for key, value in coverage["verdict_counts"].items())
    )
    print("  flags: " + ", ".join(f"{key}={value}" for key, value in coverage["flags"].items()))
    print("\nMetrics")
    print(f"  accuracy: {metrics['accuracy']:.3f}")
    print(f"  macro F1: {metrics['macro_f1']:.3f}")
    print(f"  misleadingness recall: {metrics['misleadingness_recall']:.3f}")
    print("  verdict              support  precision  recall  f1")
    for verdict in VERDICTS:
        row = metrics["per_class"][verdict]
        print(
            f"  {verdict:20} {row['support']:>7}  {row['precision']:>9.3f} "
            f"{row['recall']:>6.3f} {row['f1']:>5.3f}"
        )
    print(f"  gate downgrade rate: {metrics['gate_downgrade_rate']:.3f}")
    fallback = metrics["consistency_fallback_rate"]
    print(
        f"  consistency fallback rate: {fallback if fallback is not None else 'n/a (no rendering)'}"
    )
    print(f"  latency p50/p95: {metrics['latency_p50_ms']} / {metrics['latency_p95_ms']} ms")
    print(f"  cache hit rate (<1500 ms): {metrics['cache_hit_rate']}")
    print(f"  cost: ${metrics['cost_usd']:.6f} (${metrics['cost_per_check_usd']:.6f}/check)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fact Spreader labelled evaluation")
    parser.add_argument("--set", default="../tests/eval/claims.jsonl", help="labelled JSONL set")
    parser.add_argument(
        "--predictions",
        default="../tests/eval/predictions.baseline.jsonl",
        help="predictions JSONL",
    )
    parser.add_argument(
        "--live", action="store_true", help="run real checks and record predictions"
    )
    parser.add_argument(
        "--fast", action="store_true", help="use fast mode instead of the full pipeline"
    )
    parser.add_argument("--limit", type=int, default=0, help="score only the first N cases")
    parser.add_argument("--concurrency", type=int, default=4, help="parallel checks in live mode")
    parser.add_argument("--timeout", type=float, default=240.0, help="per-check timeout in seconds")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key-file", default="../.local/api-key")
    parser.add_argument("--out", default=None, help="where --live writes predictions")
    parser.add_argument("--check-only", action="store_true", help="validate the set and exit")
    args = parser.parse_args()

    cases = load_cases(Path(args.set))
    coverage = check_coverage(cases)
    if args.check_only:
        print(json.dumps(coverage, indent=2))
        return

    if args.live:
        key_path = Path(args.api_key_file)
        if not key_path.exists():
            _fail(f"API key file {key_path} does not exist")
        api_key = key_path.read_text(encoding="utf-8").strip()
        if not api_key.startswith("fc_live_"):
            _fail("the API key file does not contain an fc_live_ key")
        out = Path(args.out or args.predictions)
        predictions = run_live(
            cases,
            base_url=args.base_url,
            api_key=api_key,
            fast=args.fast,
            limit=args.limit,
            budget_seconds=args.timeout,
            out=out,
            concurrency=args.concurrency,
        )
        metrics = score(cases, predictions)
    else:
        predictions = load_predictions(Path(args.predictions))
        metrics = score(cases, predictions)
    _print_report(metrics, coverage)


if __name__ == "__main__":
    main()
