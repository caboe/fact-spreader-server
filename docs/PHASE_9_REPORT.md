# Phase 9 report — evaluation, hardening, packaging and acceptance

Date: 2026-11-17. Status: **agent work is implemented; the live acceptance checks are
blocked by the provider account balance.** DeepSeek returns `402 Insufficient Balance` on
every chat/moderation call as of 23:17. The recorded evaluation, `backup-test`, the
full check through Caddy and the clean-start acceptance all need a model call, so they
stopped there. Nothing below claims more than ran.

## What is built

### Labelled evaluation

The carried-over set had 136 rows with duplicated ids and 43 texts repeated four times, no
`contested` case and no flags. It is now `tests/eval/claims.jsonl`: 25 unique cases, all
seven verdicts, the four required flags, a contradiction case, a German-only cross-lingual
case, a quote-context case, two stale cases and two injection cases. The moderation set was
deduplicated from 135 rows to 30 unique cases. `make eval-check` enforces unique ids,
verdict coverage, flag coverage and a minimum size; an empty set or prediction file fails.

`backend/app/tools/eval.py` provides:

- `make eval-recorded` — offline replay of a committed predictions file, no network/model;
- `make eval-live` — real checks, then rewrites the predictions baseline;
- metrics: per-verdict precision/recall/F1, macro-F1, misleadingness recall, gate-downgrade
  rate, consistency-fallback rate, latency p50/p95, cache-hit proxy and cost per check.

The live runner submits full checks asynchronously with configurable concurrency, accepts
the sync `200` fast-mode response, retries transient `429/502/503/504`, refuses to score a
missing prediction and writes predictions as JSONL.

### Security hardening

- Upload magic bytes now win over a user-supplied extension: a PNG renamed `.md` is
  rejected, a PDF with a wrong extension is parsed as PDF.
- New tests cover ZIP traversal, absolute paths, symlinks, a compression bomb, image magic
  bytes, SSRF redirect to loopback and a hostname resolving to a private address.
- `backend/app/main.py` documents the problem+json error envelope and the non-JSON
  responses (`text/event-stream`, `text/csv`, `text/markdown`) in OpenAPI.
- Schemathesis against the live `/v1` (read-only methods, 159 generated cases) now passes
  **all** checks: no 5xx, no undocumented status codes, content type and response schemas
  conform.
- The permission matrix still covers every protected route; the new moderation probe
  requires explicit `confirm` so the matrix does not spend a model call.

### Edge and operations

- `deploy/caddy/Dockerfile` builds the static SPA and serves it with Caddy (internal CA in
  development) next to `/api`, `/v1` (SSE flushed), `/healthz` and `/readyz`.
- `/internal/*` and `/metrics` return `404` at the edge. The SPA and `/v1/instance` answer
  `200` through `https://localhost:8443`; SSE reaches the client (`event: state` and
  keepalives were read through the edge).
- `make backup` dumps the application database (uploaded originals are in
  `document_versions.raw_bytes`), writes a summary and checksums. This ran.
- `make backup-test` restores into a throwaway Compose project on alternate ports,
  reindexes the derived LightRAG corpus and runs a check. The script is written but not
  completed because reindex/check need the provider.
- Docs: `docs/EVALUATION.md`, `docs/SECURITY.md`, `docs/OPERATING.md`, updated README and
  quick start, CI workflow with `make verify`, web build, `make eval-recorded` and the
  screenshots/evaluation artifact; a secret-gated live smoke job.

## What actually ran

- `make verify`: format/lint/typecheck, unit tests, integration tests (Testcontainers,
  fakes), migration up/down/up, OpenAPI drift, compose guard and web check — green on the
  committed tree after the generated client was committed.
- `make schemathesis`: 159 / 159 checks passed on the read-only `/v1` surface.
- `make backup`: dump, summary and SHA256SUMS verified.
- The fixture corpus was seeded: 10 documents indexed, corpus version bumped.
- Caddy: SPA and API through HTTPS, internal/metrics blocked, SSE initial event and
  keepalive through the proxy.
- A 25-case live evaluation against the **unseeded** corpus completed before the fixtures
  were indexed: accuracy 0.480, macro-F1 0.392, misleadingness recall 0.167, latency p50
  13.4 s / p95 54.0 s, cost $0.066 (recorded in the run output). Because the live corpus did
  not contain the fixture documents at that moment, these numbers do **not** measure the
  labels and are not committed as the baseline.

## Blocked

DeepSeek answered `402 Insufficient Balance` for every chat and moderation call after the
first evaluation pass. The key is the one supplied earlier; the account balance is
exhausted, not a code failure. Consequently:

- the seeded evaluation did not finish and no `tests/eval/predictions.baseline.jsonl` is
  committed; `make eval-recorded` honestly fails without it;
- `make backup-test` cannot rebuild the corpus or run its check;
- a full browser check through Caddy (SSE → report) cannot pass moderation;
- the clean-start acceptance (fresh volumes → wizard with provider test → first check) is
  blocked at the provider step.

Resume with a topped-up/new DeepSeek key (or an approved local model), then run:

```bash
make eval-live
make backup
make backup-test
# fresh-volume acceptance in a disposable project
```

## Spend

Post-fresh-volume ledger: **USD 0.471579** (219 checks, 248 results; probes, setup,
LightRAG indexing, the evaluation passes and cancelled test jobs included). Cumulative
across the project: **USD 1.118533 of USD 15.00**.

## Known limitations

- The eval set is small (25 cases) and synthetic; a second rater and a larger set are
  future work. A table/figure-only case is absent because the fixture corpus has no such
  document.
- `make schemathesis` covers read-only methods only; state-changing fuzzing would mutate
  the instance and needs a disposable stack.
- Dependency audit (`pip-audit`, `pnpm audit`) is documented but not in CI.
- The edge uses Caddy's internal CA in development; production needs a real certificate.
- API-key management UI, retention/four-eyes/backup settings and the persona test console
  remain deferred from Phase 8.
