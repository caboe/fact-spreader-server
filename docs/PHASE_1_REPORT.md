# Phase 1 report — vertical slice

**Date:** 2026-11-17. **Plan:** [`IMPLEMENT.md`](../IMPLEMENT.md) §4. **Status:** complete.

This report records what actually ran, not what was intended. The regular suite never
called a network; every live call went through the internal gateway and is in the usage
events. No provider key, API key or password appears in the repository, the generated
artefacts or the compose logs (checked by comparing the local secret values against the
logs without printing them).

## What the slice does

A text claim enters `POST /v1/factcheck`, is moderated, becomes a durable Postgres job, is
processed by the worker, retrieves approved passages from stock LightRAG through
`POST /query/data`, gets a schema-validated verification/audit proposal, and is reduced by
pure code to a verdict, gate, contradiction/recency result and a deterministic substance
report. The result is stored and served by `GET /v1/factcheck/{job_id}`. A minimal SSE
endpoint emits `state` and `done`; statement/result streaming is Phase 2.

The corpus contains six synthetic crime fixtures, explicitly approved by
`seed-fixtures --approve` with the admin recorded as approver. Ingestion is real: the
documents are embedded and extracted by stock LightRAG through the internal gateway.

## Observed results

### Stack

- PostgreSQL 16.16 with pgvector 0.8.0 and Apache AGE 1.5.0-rc0; separate `app` and
  `lightrag` databases.
- Redis 7.4, backend and worker built from the pinned image, stock
  `ghcr.io/hkuds/lightrag:v1.5.0`.
- `/healthz` 200; `/readyz` reported `database`, `redis`, `lightrag` and `moderation` all
  true after bootstrap.
- Postgres, Redis and LightRAG survived a host crash; backend/worker were recreated and
  the canonical result was still retrievable after a restart.

### Canonical claim

Input: `Immigrants commit more crimes. That's just what the statistics say.`

```
overall_verdict: true_but_misleading
statements: 2 (one factual, one rhetoric/non-checkworthy)
evidence: 6, all tier 1, provenance grade A
gate: {"required": 1, "independent_sources": 4, "min_quality": "B",
       "downgraded": false, "reason": null}
warnings: []
```

The six sources are the raw BKA suspect table, the adjusted study, the conviction data,
the age curve, the shared-dataset adjusted study and the German PKS methodology note
(displayed in the original German with provenance; translation is a Phase 2/3 feature).
The report's missing-context items cite their own evidence; the reason codes are from the
contract (`no_disaggregated_data`, `quote_context_unavailable`, `other`).

Latency of the three successful canonical runs: 37.7 s, 44.8 s, 72.8 s (p50 44.8 s, p95
72.8 s). The later runs are slower because the verification call gets more output budget;
the targets are p50 < 60 s and p95 < 120 s, so the observed runs are inside the targets.

### No-evidence claim

Input: `Germany's crime rate doubled in 2024.` → `insufficient_evidence`, no fabricated
citations, no matching document. The earlier vague probe
`The 2026 revision changed the rules again.` was treated by the extractor as non-checkable;
the extraction prompt now says that under-specified empirical claims are still checkworthy.

### Moderation

- `Explicit sexual content involving a minor.` → status `refused`, action `block`, no
  statements, no extraction call. Blocked by the deterministic floor in front of the LLM
  classifier (D11).
- The canonical discriminatory claim was flagged as a `discriminatory_generalization` with
  action `flag_only` and was still checked. This is the intended check-input policy.
- With the moderation backend forced unavailable, the integration test receives `503
  moderation_unavailable` and no job is created.

### Idempotency and failure handling

- The integration test sends the same body twice with one `Idempotency-Key` and observes the
  same job id and exactly one job.
- A failed job returns `200` with the job error instead of an endless `202` (found during
  the first live run).
- The worker re-fetches the job inside its own session, so the done state and result id are
  persisted (found during the first live run; the result had been saved while the job stayed
  `running`).

## Commands that ran

```bash
make install                 # uv sync --frozen; audited 59 packages
make verify                  # formatting, lint, mypy, unit, integration, migrations,
                             # OpenAPI drift, compose pin checks — all passed
make stack-up                # build + start; postgres, redis, backend, lightrag, worker
make bootstrap               # instance, admin, providers/models, smoke API key
make seed-fixtures           # 6 fixtures approved and indexed; LightRAG idle
make stack-smoke             # canonical, no-evidence, moderation block; SMOKE OK
docker compose restart backend worker
```

Test counts: **35 unit**, **9 integration**, migration up/down/up + `alembic check`,
`compose-check` (pinned images, no Docker socket, no host network), OpenAPI current.

## Live-model spend

Approved cap: **USD 15 total, hard stop USD 20**. Spend through Phase 1:

| Consumer | Calls | Tokens in | Tokens out | Estimated USD |
| --- | ---: | ---: | ---: | ---: |
| pipeline | 38 | 81,853 | 102,400 | 0.075754 |
| lightrag | 57 | 65,511 | 35,069 | 0.034905 |
| moderation | 12 | 4,082 | 1,242 | 0.001848 |
| **total** | **107** | | | **0.112507** |

This includes one failed verification attempt (all output tokens consumed by reasoning) and
earlier smoke iterations. Embedding calls are local `bge-m3` and cost USD 0. Costs are
estimated from the configured per-million-token prices in the gateway; the meter is the
provider's usage field.

## Known limitations (all planned)

- Text input only; file, URL and image return an explicit `422`/Phase 2.
- No persona narration, consistency judge or OpenAI-compatible chat surface yet.
- Minimal SSE only (`state`, `done`); no statement/result events, no cancellation.
- No claim archive list/detail endpoints beyond `/v1/usage/me`; no research, fast mode,
  cache, editorial document API, web UI or Caddy.
- The fixture publishers `Example …` get a document-level grade override for evaluation
  (D12); this is synthetic data, not a shipped-list judgement.
- The Phase 1 verify ran in the working tree, not from a fresh clone; the clean-checkout
  reproduction is part of Phase 9 acceptance.
