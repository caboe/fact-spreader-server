# Phase 9 report — evaluation, hardening, packaging and acceptance

Date: 2026-11-18. All Phase 9 agent checks ran. The final human acceptance is open.

## Evaluation

The carried-over set had 136 rows with duplicated ids and 43 texts repeated four times, no
`contested` case and no flags. It is now `tests/eval/claims.jsonl`: 25 unique cases, all
seven verdicts, the four required flags, a contradiction case, a German-only cross-lingual
case, a quote-context case, two stale cases and two injection cases. The moderation set was
deduplicated from 135 rows to 30 unique cases. `make eval-check` enforces unique ids,
verdict/flag coverage and a minimum size; an empty set or prediction file fails.

`backend/app/tools/eval.py` provides `make eval-recorded` (offline replay, no network or
model), `make eval-live` (real checks, incremental predictions so an interrupted run
resumes, then rewrites the baseline) and metrics: per-verdict precision/recall/F1,
macro-F1, misleadingness recall, gate-downgrade rate, consistency-fallback rate, latency
p50/p95, cache-hit proxy and cost per check.

The fixture corpus was seeded in full: 23 documents approved and indexed. Fixture
publication dates were refreshed to 2026 except the two deliberately stale documents, so
the staleness rule measures what the labels intend. The full 25-case run took
`tests/eval/predictions.baseline.jsonl`; `make eval-recorded` reproduces it offline.

| Metric | Value |
| --- | --- |
| Cases / no verdict | 25 / 0 |
| Accuracy | 0.640 |
| Macro-F1 | 0.625 |
| Misleadingness recall | 0.333 |
| True precision / recall | 1.000 / 0.833 |
| True-but-misleading precision / recall | 0.667 / 0.333 |
| False precision / recall | 1.000 / 1.000 |
| Contested precision / recall | 0.500 / 1.000 |
| Gate-downgrade rate | 0.160 |
| Latency p50 / p95 | 16.3 s / 71.2 s |
| Cost | $0.0812 ($0.003248/check) |

Two pipeline issues surfaced during the evaluation and were fixed before the baseline:

1. Retrieval recomputed publisher grades and ignored the document-level override, so every
   fixture source was graded D and every supported claim became `insufficient_evidence`.
   The runner now honours `source_quality_basis.source == "document_override"`.
2. Verification output hit the 8k-token cap on the larger evidence set and was cut
   mid-JSON (`invalid_model_output`). Verification candidates are capped at six and the
   prompt asks for a compact output (at most 6 evidence links, 3 points per list, 120-word
   rationale).

## Security and contracts

- Upload magic bytes win over a user-supplied extension: a PNG renamed `.md` is rejected, a
  PDF with a wrong extension is parsed as PDF.
- New tests cover ZIP traversal, absolute paths, symlinks, a compression bomb, image magic
  bytes, an SSRF redirect to loopback and a hostname resolving to a private address.
- OpenAPI documents the problem+json error envelope and the non-JSON responses
  (`text/event-stream`, `text/csv`, `text/markdown`).
- Schemathesis on the live `/v1` read-only surface: **159 / 159 checks passed** — no 5xx,
  no undocumented status codes, content type and response schemas conform.
- The moderation probe requires explicit `confirm`, so the permission matrix cannot spend a
  model call; the matrix still covers every protected route.

## Edge, backups and clean start

- `deploy/caddy/Dockerfile` builds the static SPA; Caddy serves SPA, `/api`, `/v1` (SSE
  flushed), `/healthz` and `/readyz` over HTTPS with its internal CA. `/internal/*` and
  `/metrics` return `404`. A real browser check went through `https://localhost:8443`,
  streamed over SSE and opened the report.
- `make backup` dumps the application database (uploaded originals are in
  `document_versions.raw_bytes`), writes a summary and SHA256SUMS; checksums verified.
- `make backup-test` restored the dump into a disposable project on alternate ports and ran
  one check: **passed**, verdict `insufficient_evidence`. The restored LightRAG volume is
  derived and not part of the backup; re-indexing after a restore remains the documented
  recovery step.
- `make clean-start-test` started a second project with empty volumes, completed the setup
  wizard (admin, TOTP, organization, provider test, chat and embedding assignments,
  moderation) and ran the first check: **passed**, verdict `insufficient_evidence`.
  The active provider key was passed through `CLEAN_DEEPSEEK_API_KEY` because `.env` still
  holds the older, depleted key.
- Docs: `docs/EVALUATION.md`, `docs/SECURITY.md`, `docs/OPERATING.md`, updated README and
  quick start; CI workflow with `make verify`, web build, `make eval-recorded`, the
  screenshots/evaluation artifact and a secret-gated live smoke job.

## What ran

- `make verify` — format/lint/typecheck, unit tests (including the new eval and upload
  tests), integration tests, migration up/down/up, OpenAPI drift, compose guard, web check.
- A clean checkout (`git clone` into `.local/clean-checkout`, `make install`,
  `make verify`) — green.
- `make eval-recorded` — metrics above, offline.
- `make schemathesis` — 159 / 159.
- `make backup`, `make backup-test` — both passed.
- `make clean-start-test` — passed.
- Browser check through Caddy — passed.
- Spend: post-fresh-volume ledger **USD 0.950295** (301 checks, 324 results; setup,
  indexing, evaluation passes, acceptance runs and cancelled test jobs included).
  Cumulative across the project: **USD 1.597249 of USD 15.00**.

## Known limitations

- The eval set is small (25 cases) and synthetic; a second rater and a larger set are
  future work. A table/figure-only case is absent because the fixture corpus has no such
  document. The metrics measure this corpus, not factual accuracy in general.
- Schemathesis covers read-only methods; state-changing fuzzing needs a disposable stack.
- `backup-test` verifies the restored application state and check path; it does not
  re-index the derived corpus in the disposable project (re-index is exercised separately).
- Dependency audit (`pip-audit`, `pnpm audit`) is documented but not in CI.
- The edge uses Caddy's internal CA in development; production needs a real certificate.
- API-key management UI, retention/four-eyes/backup settings and the persona test console
  remain deferred from Phase 8.

## Human gate

Final acceptance: compare the delivered behaviour and UI with `PURPOSE.md`, run the
extension test when the extension exists and approve the release. The agent stops here.
