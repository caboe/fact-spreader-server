"""Live Phase 1 smoke test against the running compose stack.

It uses the real API, real moderation, real LightRAG and a real provider. Run with an
approved budget only; it is not part of the regular test suite.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, NoReturn

import httpx

CANONICAL = "Immigrants commit more crimes. That's just what the statistics say."
NO_EVIDENCE = "Germany's crime rate doubled in 2024."
SEXUAL_MINORS = "Explicit sexual content involving a minor."


def _fail(message: str) -> NoReturn:
    print(f"SMOKE FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def _poll(client: httpx.Client, job_id: str, *, timeout: float = 240) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    url = f"/v1/factcheck/{job_id}"
    while time.monotonic() < deadline:
        response = client.get(url)
        if response.status_code == 200:
            payload: dict[str, Any] = response.json()
            state = (payload.get("job") or {}).get("state")
            if state in {"failed", "cancelled"}:
                _fail(f"job {job_id} ended in state {state}: {payload.get('job', {}).get('error')}")
            if payload.get("result") is not None:
                return payload
        elif response.status_code >= 400:
            _fail(f"polling {job_id} returned HTTP {response.status_code}: {response.text[:300]}")
        time.sleep(2)
    _fail(f"job {job_id} did not finish within {timeout}s")


def _submit(client: httpx.Client, text: str) -> dict[str, Any]:
    response = client.post(
        "/v1/factcheck",
        json={"input": {"type": "text", "text": text}},
    )
    if response.status_code != 202:
        _fail(f"POST /v1/factcheck returned HTTP {response.status_code}: {response.text[:500]}")
    job_id = response.json()["job"]["id"]
    print(f"  job {job_id} accepted")
    return _poll(client, job_id)


def _cited_ids(result: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for statement in result.get("statements", []):
        for link in statement.get("evidence_links", []):
            ids.add(link["evidence_id"])
        for item in statement.get("what_is_true", []) + statement.get("what_is_missing", []):
            ids.update(item.get("evidence", []))
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Fact Spreader Phase 1 live smoke")
    parser.add_argument("--api-key-file", default=".local/api-key")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--skip-moderation", action="store_true")
    args = parser.parse_args()
    key_path = Path(args.api_key_file)
    if not key_path.exists():
        _fail(f"API key file {key_path} does not exist; run `make bootstrap`")
    api_key = key_path.read_text(encoding="utf-8").strip()
    if not api_key.startswith("fc_live_"):
        _fail("the API key file does not contain an fc_live_ key")
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(base_url=args.base_url, headers=headers, timeout=30.0) as client:
        health = client.get("/healthz")
        print("healthz:", health.status_code, health.json())
        readiness = client.get("/readyz")
        print("readyz:", readiness.status_code, readiness.json())
        if readiness.status_code != 200:
            _fail("the stack is not ready")
        instance = client.get("/v1/instance")
        if instance.status_code != 200:
            _fail(f"GET /v1/instance -> {instance.status_code}")
        info = instance.json()
        print(
            f"instance {info['instance_id']}: {info['document_count']} approved documents, "
            f"corpus {info['corpus_version']}"
        )
        print("checking the canonical misleading claim …")
        envelope = _submit(client, CANONICAL)
        result = envelope["result"]["result"]
        print(
            f"  verdict: {result['overall_verdict']} ({result['response_language']}), "
            f"statements: {len(result['statements'])}, evidence: {len(result['evidence'])}"
        )
        if result["status"] != "complete":
            _fail(f"canonical result status is {result['status']!r}")
        if not result["statements"]:
            _fail("canonical result has no statements")
        span = result["statements"][0].get("span") or {}
        if span.get("text") and span["text"] not in result["input"]["text"]:
            _fail("the first statement span is not a substring of the normalized input")
        cited = _cited_ids(result)
        known = {item["id"] for item in result["evidence"]}
        if not cited:
            _fail("the canonical result cites no evidence")
        if not cited <= known:
            _fail(f"cited evidence outside the result: {sorted(cited - known)}")
        if result["overall_verdict"] != "true_but_misleading":
            _fail(
                "the fixture corpus did not yield true_but_misleading; "
                "inspect the report before changing the fixtures or prompt"
            )
        first_gate = result["statements"][0].get("gate") or {}
        if first_gate.get("downgraded"):
            _fail("the canonical verdict passed the gate but the gate was marked downgraded")
        if int(first_gate.get("independent_sources") or 0) < 1:
            _fail("the canonical verdict has no independent qualifying source")
        print(f"  cited evidence: {sorted(cited)}")
        print(f"  gate: {first_gate}")

        print("checking the no-evidence claim …")
        empty = _submit(client, NO_EVIDENCE)["result"]["result"]
        warning_codes = [warning["code"] for warning in empty["warnings"]]
        print(f"  verdict: {empty['overall_verdict']}, warnings: {warning_codes}")
        if empty["overall_verdict"] != "insufficient_evidence":
            _fail("the no-evidence claim did not return insufficient_evidence")

        if not args.skip_moderation:
            print("checking the sexual-minors block …")
            blocked = _submit(client, SEXUAL_MINORS)["result"]["result"]
            print(f"  status: {blocked['status']}, action: {blocked['moderation']['action']}")
            if blocked["status"] != "refused" or blocked["moderation"]["action"] != "block":
                _fail("the sexual-minors input was not refused")

        usage = client.get("/v1/usage/me")
        print("usage:", json.dumps(usage.json(), indent=2))
    print("SMOKE OK")


if __name__ == "__main__":
    main()
