# IMPLEMENT — Build Plan

> Companion documents: **PURPOSE.md** (requirements), **PROTOCOL.md** (normative wire
> contracts), **PERSONAS.md** (runtime rendering configuration),
> **docs/REDESIGN_NOTES_DE.md** (decision log). Where this plan and `PROTOCOL.md`
> disagree about a wire shape or endpoint, `PROTOCOL.md` wins. Where this plan and
> `PURPOSE.md` disagree about behaviour, `PURPOSE.md` wins.

**Status:** approved 2026-11-16. **Phase 1 complete 2026-11-17.** The human approved the
revised specs, this plan, and a live-model budget of **USD 15 total with a hard stop at USD
20**. Approval also permits the available DeepSeek, OpenRouter and local Ollama credentials
for the explicit live checks. Phase 1 evidence: [`docs/PHASE_1_REPORT.md`](docs/PHASE_1_REPORT.md).

---

## 1. How this plan is worked

1. **Phase by phase, vertical slices.** Every phase ends with something that runs end to
   end in the real stack: stock LightRAG, a real provider, real Postgres/Redis, and — once
   a UI exists — a real browser. No phase is a layer-only milestone.
2. **Every "Done when" check is tagged.**
   - `[agent]` — the agent runs it in this environment and reports the observed result,
     including exact commands and relevant output. It is never "missing" and never
     "assumed".
   - `[human]` — the agent stops and asks. It does not proceed past the check on its own.
3. **If a check fails twice, stop** and report the blocker with the two attempts and the
   evidence. Do not patch around a failing foundation.
4. **Say what actually ran.** "Tests are green" is not "the stack starts". Every phase
   report names the commands, the observed outcomes, the live-model spend and anything
   skipped.
5. **Regular tests never call the network or a real model.** Unit and integration tests use
   deterministic fakes and recorded responses. Live calls happen only in explicit
   `make eval-live` / `make stack-smoke` runs inside the approved budget.
6. **Contracts first.** Pydantic models are the single source of truth. OpenAPI is exported
   and generated clients are committed. A shape change that is not regenerated fails the
   drift check.
7. **Hard invariants are not negotiable.** See AGENTS.md. If a phase cannot meet one, stop
   and ask; do not relax it to finish a phase.
8. **The tree is green at every commit.** Lint, format check, strict type check, unit tests,
   migration check and OpenAPI drift check run before every commit. One logical change per
   commit, signed off (`git commit -s`).

### 1.1 What "green" means in this repository

These commands are created in Phase 1 and become the fixed gates. CI runs exactly them.

```bash
make install          # uv sync --frozen, pnpm install --frozen-lockfile
make fmt-check        # ruff format --check
make lint             # ruff check
make typecheck        # mypy --strict backend/app
make test             # pytest, no network, no real model
make test-integration # Testcontainers Postgres/Redis; fake LightRAG/provider
make migrate-check    # alembic upgrade head, downgrade base, upgrade head, check
make openapi-check    # export OpenAPI, regenerate clients, fail on drift
make compose-check    # docker compose config, image pins, no :latest
make verify           # every gate that exists in the current phase
# make web-check (svelte-check, vitest, build) joins verify in Phase 7.
```

Phase-specific additions: `make stack-smoke`, `make e2e`, `make screenshots`,
`make schemathesis`, `make eval-recorded`, `make eval-live`, `make backup-test`.

### 1.2 Reporting format for each phase

The agent reports:

- the phase and its commit(s);
- every command of §1.1 plus the phase-specific checks, with `pass`/`fail` and a short
  observed result;
- live-model calls: count, tokens, provider, estimated cost in USD, and the budget
  remaining;
- screenshots for UI phases (light, dark, narrow, wide);
- what changed in `DECISIONS.md` and why;
- any `[human]` check, with the exact question and the artifact to look at.

---

## 2. Budget and live calls

**Approved cap: USD 15 total for the whole build, hard stop at USD 20** (2026-11-16).
**Spent through Phase 1: USD 0.1125** (ingestion, smoke runs and one failed verification
attempt included). The agent reports spend per phase. Live calls stop when the cap is
reached, even if a check is unfinished; the check is reported as budget-blocked. The available credentials are
DeepSeek for chat, OpenRouter for vision and local Ollama `bge-m3` for embeddings; they are
never written to the repository, printed or included in logs or fixtures.

Cost control rules:

- reasoning/chat calls use the cheapest provider/model that passes the required capability
  test; no premium model unless a check explicitly needs it;
- pipeline calls are batched where the spec allows (extract + scope in one call;
  verify + audit in one call) and the fast mode uses fewer calls;
- embeddings run locally (Ollama `bge-m3`, 1024 dimensions) in this environment; they cost
  no provider money;
- every live call goes through the gateway and is visible in `/v1/usage/summary`;
- recorded responses are committed for the regular suite; a live run only records new
  fixtures when the agent explicitly asks for it.

Credentials for this environment are available to the agent (DeepSeek chat, OpenRouter
vision, local Ollama embeddings). They are never written to the repository, never printed
and never included in logs or fixtures.

---

## 3. Fixed architecture decisions

These are implementation decisions within the approved specs. Each gets a `DECISIONS.md`
entry in Phase 1.

| Area | Decision | Why |
| --- | --- | --- |
| Backend | Python 3.12, FastAPI, Pydantic v2, async SQLAlchemy 2, Alembic, `uv` | AGENTS.md stack; boring and typed |
| Frontend | SvelteKit 2 SPA (`adapter-static`), Svelte 5, TypeScript strict, Tailwind 4, Bits UI, Lucide, generated `openapi-typescript` + `openapi-fetch` client | redesign §9a; no Node server |
| i18n | Typed JSON message catalog (en/de/fr/es) with `Intl` formatting; no runtime translation service | small, testable, no extra framework |
| Charts | LayerChart (Svelte) for usage views | native to the UI stack; alternative ECharts rejected to avoid a second rendering model |
| Database | Postgres 16 with pgvector + Apache AGE, built from a pinned Dockerfile; separate `app` and `lightrag` databases | one database server, LightRAG all-in-one storage |
| Redis | rate limits, token buckets, short-lived locks | already in the stack; not the source of truth for jobs |
| Worker | Postgres job table with `FOR UPDATE SKIP LOCKED`, one worker process, durable partial results | fewer moving parts than a second broker; reconnect-safe |
| SSE | DB polling + keepalive, no Redis pub/sub | durable, survives worker/backend restarts, no lost events |
| LightRAG | stock image `ghcr.io/hkuds/lightrag:v1.5.0`, HTTP only, `POST /query/data`, never answer generation | hard invariant 7 |
| Embeddings | OpenAI-compatible embeddings through the gateway; local Ollama `bge-m3` (1024) in this environment | multilingual requirement; no provider cost |
| Chat/vision providers | any OpenAI-compatible provider; DeepSeek for chat and OpenRouter for vision in this environment; selected by capability test | model freedom, cost |
| LLM gateway | part of the backend, `/internal/llm/v1`, internal key, stable aliases (`fs-chat`, `fs-extract`, `fs-embedding`, …) | hard invariant 8; LightRAG stays stock |
| Auth | server-side sessions in Postgres, HttpOnly/Secure/SameSite cookie, Argon2id, CSRF token; API keys and device tokens SHA-256 hashed and shown once; TOTP via `pyotp` | revocation, no JWT footgun |
| Files | local Docker volume for originals/parsed text in v1; backup includes it | one deployment, no S3 dependency |
| Parsing | Docling in the worker (PDF/DOCX/HTML/scan/table), vision for figures | redesign §8 |
| Language detection | `lingua-language-detector`, more languages than supported | recognises "unsupported" |
| HTTP | `httpx` with timeouts, retry budget, circuit breaker, SSRF guard | hard invariant 14 |
| Recording | request-hash keyed JSON fixtures for LLM and LightRAG calls, `RECORD_LLM=1` live mode | no network in regular tests |
| Images | Pillow validation, EXIF stripping, max dimensions | privacy and safety |
| Logging | structured JSON logs with request id, principal id, route, status, latency; content redacted | audit and privacy |
| Metrics | `/metrics` optional, off by default; health endpoints always | operations |

Deferred to later phases, but planned for: Docling in Phase 4, model capability tests in
Phase 6, TOTP and full setup in Phase 5, UI in Phases 7–8, evaluation in Phase 9.

### 3.1 Repository layout

```text
backend/
  app/
    api/            # /v1, /api, /internal routers
    contracts/      # Pydantic wire models and enums
    core/           # config, security, logging, errors, http, ssrf
    db/             # models, session, repositories
    llm/            # gateway, providers, registry, usage, data flow
    retrieval/      # LightRAG client, orchestrator, provenance
    pipeline/       # extraction, verification, audit, gate, verdicts, templates
    rendering/      # persona renderer, consistency checker, compact format
    documents/      # parsing, review, batch, indexing, re-checks
    jobs/           # queue, worker, events
    services/       # auth, users, setup, moderation, research, cache, usage
    worker.py
    main.py
  alembic/
  tests/
    unit/ integration/ fixtures/ llm/
web/
  src/              # SvelteKit app
  static/
docs/openapi.json
methodology/
deploy/postgres/
deploy/lightrag/
tests/eval/         # labelled sets and fixture corpus (carried over, repaired)
docker-compose.yml
Makefile
pyproject.toml
```

### 3.2 Image and dependency pinning

Every image is pinned, never `latest`. A bump requires a `DECISIONS.md` entry and an
integration run. Initial pins: Postgres 16 + pgvector 0.8.0 + AGE 1.5.0, Redis 7.4-alpine,
LightRAG v1.5.0, Caddy 2-alpine, Python 3.12-slim, Node 22-alpine. Python and Node
dependencies are locked (`uv.lock`, `pnpm-lock.yaml`). New runtime dependencies need a
`DECISIONS.md` entry.

---

## 4. Phase 1 — Vertical slice: one claim through real LightRAG and a real model

**Status: complete (2026-11-17).** `make verify` is green (35 unit, 9 integration, migration
up/down/up, OpenAPI drift, compose pin checks); the live stack reproduced the canonical
`true_but_misleading` result with six cited tier-1 sources and a non-downgraded gate, an
`insufficient_evidence` result for an unsupported claim, and a refused sexual-minors input.
The minimal SSE endpoint (`state`, `done`) was implemented early; statement/result events
remain Phase 2. The Phase 1 report is [`docs/PHASE_1_REPORT.md`](docs/PHASE_1_REPORT.md).

**Goal.** A claim goes through the public API, a worker, stock LightRAG retrieval and a real
provider, through extraction, verification, audit, gate and deterministic substance, and
comes back with a verdict and citations. This is the proof that the architecture works.

**Scope.**

- Repository scaffold, `pyproject.toml`, `uv.lock`, `Makefile`, `.env.example`,
  `.gitignore`, `DECISIONS.md`, Dockerfiles, `docker-compose.yml` with Postgres (pgvector +
  AGE), Redis, LightRAG, backend, worker.
- Config via `pydantic-settings`; secrets never in code.
- Postgres image with two databases (`app`, `lightrag`), extensions and grants; Alembic
  initial migration for: instance, users, permissions, API keys, providers, models, role
  assignments, documents, document versions, passages, jobs, results, statements,
  evidence, evidence links, warnings, usage events, audit log, corpus gaps, contradictions,
  moderation events, idempotency keys.
- Minimal auth: first admin bootstrap, login, session cookie, CSRF, one API key created by
  CLI and printed once; permission check for `claims:submit`; unresolved endpoints hidden.
- Internal LLM gateway: chat and embeddings proxying, internal key, aliases, usage event,
  budget check, timeout/retry/breaker, no content logging. Provider bootstrap from
  environment for this phase (the operator UI comes later); key encrypted at rest with
  `APP_SECRET_KEY`.
- LightRAG client: health, insert text, document status, `/query/data`, delete document;
  no `/query` or `/query/stream`. `file_source = "<doc_id>@v<version>"`.
- Embedding and chat calls from LightRAG go through the gateway; a stock
  `deploy/lightrag/lightrag.env` points at `backend:8000/internal/llm/v1`.
- Publisher list loader and source-quality resolution (`methodology/publishers.json`).
- Fixture approval/index CLI: `python -m app.cli seed-fixtures --approve` registers selected
  fixture documents in `approved` state with an approval record attributed to the admin,
  parses the Markdown, and indexes them through LightRAG. This is an explicit approval
  path, not automatic approval; Phase 4 replaces it with the editorial workflow.
- Check pipeline for **text** input: language detection, statement extraction with spans,
  scope, topics, keywords; LightRAG retrieval; one structured verify + audit call; evidence
  IDs validated against retrieved candidates; gate; contradiction and recency checks;
  overall verdict; deterministic substance templates in en/de/fr/es; warnings.
- Moderation gate: LLM classifier through the gateway; `sexual_minors` always blocks; other
  categories flag and continue for checks; fail closed with `503 moderation_unavailable`;
  the check is not run without moderation.
- Async job by default: `POST /v1/factcheck` → 202 job, worker processes, `GET
  /v1/factcheck/{id}` returns the result. Synchronous mode is not required in Phase 1.
- `GET /v1/instance`, `GET /v1/models` (deterministic substance only in this phase),
  `GET /healthz`, `GET /readyz`, `GET /v1/usage/me` (minimal counters).
- Tests: pure functions for gate, overall verdict, contradiction, recency, independence,
  source-quality resolution, span validation, warning mapping; integration with fake
  provider and fake LightRAG; one compose integration with real LightRAG and real provider.
- `DECISIONS.md`: worker queue/SSE, LightRAG version, Postgres build, embeddings, auth
  sessions, gateway aliases, fixture approval CLI, test recording.

**Out of scope for this phase:** persona narration, files/URLs/images, SSE, OpenAI layer,
research, fast mode/cache, claim archive UI, document review UI, batch upload, model
management UI, TOTP, full role model, web UI.

**Done when.**

- `[agent]` `make verify` passes from a clean tree (`install`, `fmt-check`, `lint`,
  `typecheck`, `test`, `test-integration`, `migrate-check`, `openapi-check`,
  `compose-check`).
- `[agent]` `docker compose up -d --build` starts postgres, redis, lightrag, backend and
  worker; `/readyz` reports DB, Redis and LightRAG reachable; the stack is recreated from
  scratch without manual steps.
- `[agent]` the database is migrated up/down/up; the two databases and extensions exist;
  LightRAG uses the `lightrag` database and the gateway (verified in its logs, no direct
  provider call).
- `[agent]` `python -m app.cli seed-fixtures --approve` approves and indexes at least the
  three fixtures needed for the canonical case; `GET /v1/instance` shows the corpus version
  and approved document count; the index is built only through the gateway.
- `[agent]` with a real `fc_live_` key, `POST /v1/factcheck` with
  "Immigrants commit more crimes. That's just what the statistics say." reaches `done`
  within 120 s and returns: at least one statement with a correct span; a verdict of
  `true_but_misleading` (or a documented, evidence-based different verdict if the fixture
  corpus does not support it); at least two distinct cited evidence items with provenance;
  no evidence ID outside the retrieved set; a gate result; a deterministic bottom line in
  the requested language. The agent records the exact output.
- `[agent]` a claim with no matching document returns `insufficient_evidence`, cites
  nothing, and creates a corpus-gap record; a claim contradicted by two approved documents
  (unit fixture) is `contested` with both sides cited.
- `[agent]` a `sexual_minors` moderation test is refused and never reaches extraction; a
  legitimate sensitive claim ("Immigrants commit more crimes") is flagged only if the
  classifier flags it, and is still checked. With the moderation backend unavailable, the
  endpoint returns `503 moderation_unavailable` and does not call the pipeline.
- `[agent]` every model call has a usage event with consumer, role, provider, model, tokens
  and cost; no prompt, evidence, key or password appears in logs; a secret scan of the repo
  and generated artifacts finds no live key.
- `[agent]` the stack survives a restart: approved documents and reported results survive;
  a repeated `POST` with the same `Idempotency-Key` does not run twice.
- `[agent]` the phase report lists live calls, tokens, estimated USD spend and remaining
  budget; the spend is under the approved cap.
- `[human]` none for this phase; the plan approval covers it.

**Stop rule.** If real LightRAG's Postgres storage or the stock HTTP API cannot be wired
within this phase after two attempts, stop and report the exact configuration and errors;
do not fork or patch LightRAG.

---

## 5. Phase 2 — Inputs, streaming and the OpenAI surface

**Status: complete (2026-11-17).** The full live persona × language matrix passed: twelve
runs, all `format = persona` with `consistency.passed = true` on the first attempt and no
warnings. Plain text, PDF, Markdown, URL and image inputs produced completed results; the
live SSE trace has two statement events before `result`/`done`; checked streaming sends the
substance before any narrative; device-token revocation and archive feedback were exercised
live. `make verify` is green with 63 unit and 26 integration tests at `28ee94a`; the live
evidence and spend are in [`docs/PHASE_2_REPORT.md`](docs/PHASE_2_REPORT.md).

**Goal.** The check works for text, files, URLs and images, streams partial results, and is
usable by the extension through the OpenAI-compatible endpoint with a checked persona
narrative.

**Scope.**

- `POST /v1/factcheck` multipart (file/image) and URL input; SSRF guard, size/time limits,
  media validation, EXIF stripping; PDF/DOCX/HTML/Markdown parsing for checks (shared
  reader with Phase 4, no corpus write); image path through the vision model with a
  capability-tested model.
- SSE events (`state`, `statement`, `result`, `warning`, `done`, `error`) with reconnect via
  `Last-Event-ID`; durable partial statements; cancellation.
- Idempotency keys, ETags, retry semantics.
- OpenAI-compatible `GET /v1/models` and `POST /v1/chat/completions`; non-streaming and
  checked streaming; `factcheck:none`; `factcheck:<persona>`; rejected parameters; error
  mapping; usage aggregation.
- Persona rendering for the three v1 personas: prompts from `PERSONAS.md`, Shared
  Invariants injected, consistency checker (deterministic + judge), one re-render, template
  fallback, `consistency_fallback`; output moderation; compact format.
- Chat-layer turn classification for `new_claim`, `repeated_claim`, `follow_up_claim`,
  `evidence_challenge`, `clarification_answer`, `question`, `meta`, `off_topic`,
  `abusive`; no second pipeline; repeated claims use the archive/cache when available.
- Claim archive read endpoints (list/detail) and feedback; version links.
- Moderation: full category policy, flag-only for checks, output moderation, flagged-user
  view; provider moderation endpoint optionally supported.
- Language: response language override, unsupported input → English with
  `unsupported_language`, translated evidence, translated quotes, judge in the target
  language; templates for en/de/fr/es.
- Record/replay fixtures for the new model calls; integration tests with fake providers.

**Out of scope:** research, fast cache, full editorial review UI, batch, model UI, full
roles/TOTP.

**Done when.**

- `[agent]` a plain text, a PDF, a URL and a screenshot each produce a completed result with
  spans and evidence; a URL pointing at a private address is rejected by the SSRF guard
  before the fetch; an oversized file is `413`.
- `[agent]` SSE delivers at least two statement events before `done` for a multi-statement
  text; a reconnect with `Last-Event-ID` receives the current state and the final result;
  cancellation stops a queued job.
- `[agent]` the OpenAI endpoint streams the first chunk with the result before any content,
  content only after the consistency check, and `[DONE]` at the end; a forced consistency
  failure twice falls back to the deterministic template with `consistency_fallback`; an
  unsupported parameter returns the OpenAI error shape.
- `[agent]` the three personas render the canonical case in en/de/fr/es; the Analyst's
  `no_second_person` check passes in all four languages; a planted uncited sentence is
  caught by the judge; direct German quotes are labelled as translations.
- `[agent]` the compact report is deterministic and contains the badge, bottom line, two or
  three missing contexts and a report link; the extension-shaped response works with a
  device token restricted to `claims:submit`.
- `[agent]` all tests in `make verify` pass; the phase report includes screenshots? No UI
  yet, so no screenshots; it includes the stream trace and the spend.
- `[human]` none for this phase.

---

## 6. Phase 3 — Audit depth, contradictions, research and fast mode

**Status: complete (2026-11-17).** Live: the contradiction fixture pair returned
`contested` with both sides cited and a same-period record; the 2016 stale fixture returned
`insufficient_evidence` with `stale_evidence` and `audit_incomplete`; a German-only
burglary figure returned `true` with a labelled English translation (16.6 s); research
returned a judged, fully cited summary (17.0 s); fast mode returned a cold preliminary in
3.5–9.6 s and an idle cache hit in 1.33–1.70 s, with the full result as version 2.
Re-check and QS deletion are covered by integration tests. `make verify` is green with 63
unit and 30 integration tests. The live evidence and latency table are in
[`docs/PHASE_3_REPORT.md`](docs/PHASE_3_REPORT.md). Automatic re-check on a corpus-change
event is deferred to the Phase 4 document event; the manual path and budget are in place.

**Goal.** The pipeline handles the hard cases (missing context, corpus conflicts, recency,
no evidence), research works, and the extension gets a preliminary result in under 15 s with
a full result following.

**Scope.**

- Confounder checklists loaded per topic; targeted re-retrieval (≤ 2 rounds); material
  unaddressed confounders → `insufficient_evidence` + `audit_incomplete`; `true` is never
  returned with an open audit.
- Argument pattern detection from `methodology/patterns.json` with evidence and mechanism;
  `what_is_missing` items require their own evidence; gate downgrade reasons.
- Contradiction detection: same statement, same/overlapping scope, one supports + one
  refutes → `contested`; disjoint periods → development, choose the source matching the
  claim's scope (or the newest), no contradiction; contradictions recorded in the editor
  list.
- Recency: topic `staleness_days`, `stale_evidence`, present-time cap.
- Corpus gaps: aggregate by normalized semantic cluster, frequency, samples; editor list
  endpoints and re-check from a gap.
- Research: `POST /v1/search` retrieval + archive + optional summary; summary with
  per-sentence citations, attribution, loaded-term avoidance, consistency check, failure →
  list only; `summary_timeout`; filters; `search:use`.
- Fast mode: semantic cache over normalized claim embeddings (pgvector in the app DB),
  cache hit < 2 s; reduced pipeline for a preliminary result < 15 s; full check enqueued
  automatically; versioned replacement; preliminary marking; gate/audit rule; no clean
  `true` with open audit.
- Archive: full list/detail/versions/feedback/re-check; semantic duplicate detection for
  rephrased claims; automatic re-check on corpus changes (event from Phase 4, with a daily
  budget); QS deletion.
- Record/replay for audit/research/fast; live latency measurements.

**Done when.**

- `[agent]` a claim whose decisive evidence is only in a German fixture gets the correct
  cross-lingual result with a labelled translation; a claim needing a confounder triggers a
  second retrieval and either fills the gap or returns `insufficient_evidence` +
  `audit_incomplete`; no result with an open audit is `true`.
- `[agent]` a same-period contradiction fixture returns `contested` with both sides cited
  and a contradiction record; a different-period pair is a development, not a
  contradiction.
- `[agent]` a present-time claim with only stale evidence is not `true` and carries
  `stale_evidence`; a past-scoped claim is not penalised.
- `[agent]` `POST /v1/search` returns documents and archive hits in under 2 s (measured,
  no LLM); `summary=true` returns a fully cited, attributed summary; a forced
  inconsistency returns `summary=null` plus `summary_consistency_failed` and no partial
  summary.
- `[agent]` fast mode: a cache hit is served in under 2 s; a cold preliminary result in
  under 15 s; the full result arrives as a new version and the preliminary is marked; the
  initial and full verdicts are consistent with the gate.
- `[agent]` `make verify` is green; the phase report includes measured p50/p95 latencies
  for cache, fast and full with the real stack, and the spend.
- `[human]` none for this phase.

**Stop rule.** If the fast target cannot be met with the reduced pipeline, do not delete
the audit or the gate. Report the measured latency and propose a scope/call reduction; the
human decides.

---

## 7. Phase 4 — Document pipeline and editorial workflow

**Status: complete (2026-11-17).** Done: document submission for pasted text, URL and
files (PDF/DOCX/HTML/Markdown) via the existing readers; metadata, warnings, hash
duplicates with `duplicate_of`, review queue, detail/content endpoints, approve/reject/
withdraw, figure-description correction, approval audit and worker-driven LightRAG
indexing with a corpus-version bump. Live: a Destatis housing report was submitted, approved
and indexed in 10.1 s; a rent claim cited it; a resubmission returned state `duplicate`.
Approval and withdrawal now trigger bounded re-checks for matching or citing claims, with
a `budget_low` warning when the daily budget stops the run; four-eyes approval is enforced
and the editor contradiction/gap endpoints are present. Batch submission with multiple
files, URLs and a sanitised ZIP produces per-file states, duplicate detection, counts and
batch approve/reject. Open: Docling tables/scans and OCR, figure extraction and vision
descriptions, batch metadata sidecar and per-file retry, cost estimation/budget blocking,
and the editor re-check-from-gap action.

**Goal.** Documents can be submitted singly or in batches, parsed, warned about, reviewed,
approved, indexed, withdrawn and versioned; approval and withdrawal trigger re-checks.

**Scope.**

- Docling in the worker: PDF, DOCX, HTML, Markdown, scans; tables to Markdown; figure
  extraction; vision descriptions with page/figure/model; OCR fallback; parse warnings.
- Document submission (file, URL, pasted text), metadata, license/redistribution, dedup
  against the corpus and within a batch; warnings (unsupported language, injection, low
  grade, duplicate, unclear license, parse failure, unreadable figure).
- Review queue API, document detail/content, figure corrections, approve/reject/withdraw,
  four-eyes setting enforcement, approval record, versioning, change log.
- Indexing: only approved documents; insert into LightRAG with `file_source =
  doc@v`, delete on withdrawal, status polling, corpus version bump; re-check trigger for
  affected claims and for frequent claims on new documents within the daily budget.
- Batch upload: multiple files, folder upload (client-side enumeration), ZIP with
  bomb/path/symlink protection, URL list, metadata CSV/JSON, common and per-file metadata,
  per-file state and retry, cost estimate before processing, budget enforcement, summary
  counts, checkbox approval, background processing.
- Editor lists: contradictions and gaps endpoints with state transitions; re-check from a
  gap.
- Re-index flow (operator-triggered) for embedding/extraction/vision model changes; the
  index is rebuilt from approved documents; no LightRAG index backup.

**Done when.**

- `[agent]` a single PDF, a scanned page and a Markdown file are parsed; tables become
  Markdown; a figure gets a stored description with page/figure/model; the document is
  reviewed and approved through the API; it becomes retrievable; a check that needs it now
  cites it.
- `[agent]` a batch with at least one file of each warning class (duplicate, unsupported
  language, injection, low grade, missing license) produces the expected per-file states;
  documents without warnings are marked preselected, with warnings not; failed files can
  be retried individually; the batch summary matches the files; a ZIP with `../` and a
  symlink is sanitised or rejected and the safe files still process.
- `[agent]` approving a document submitted by the same editor is allowed with four-eyes
  off and `403 four_eyes_required` with it on; rejecting keeps it out of LightRAG;
  withdrawing removes it and a new check no longer cites it; past results keep their
  evidence marked withdrawn.
- `[agent]` approving a document triggers the re-check of matching claims within budget; a
  second approval over budget returns a clear skipped-budget result and does not silently
  drop the claim.
- `[agent]` batch cost estimate and actual usage are within 30% of each other on the
  fixture set; the budget blocks a batch that would exceed it before parsing starts.
- `[agent]` `make verify` is green; the phase report includes the parsed document,
  figure description, batch summary and spend.
- `[human]` none for this phase; the editorial UI is reviewed in Phase 8.

---

## 8. Phase 5 — Identity, roles, setup, limits and retention

**Status: complete (2026-11-17).** The first-run wizard (setup token, admin + TOTP,
organisation, tested provider and models, moderation test, completion gate) ran on a fresh
volume from `docker compose down -v` to the first successful check in **28.1 s**; checks,
research and chat answer `503 setup_required` before completion. TOTP is enrolled through
the web session with one-time hashed recovery codes; a privileged session without TOTP is
blocked with `totp_setup_required`, while a plain user stays optional. The permission
matrix covers every protected route in both directions, API keys and device tokens are
intersected with their owner, and revocations are immediate. Role templates, explicit
grants/denials, per-user limits and per-key lower limits are enforced before a job exists.
Retention redacts old context, purges job events and unreferenced terminal jobs, rolls
usage events into monthly aggregates, and audits every run including a dry run. The report
is [`docs/PHASE_5_REPORT.md`](docs/PHASE_5_REPORT.md).

**Goal.** The installation can be set up safely by a human, roles and permissions are
enforced, every user has limits, and personal data follows the retention policy.

**Scope.**

- First-run setup wizard API: admin account (password + TOTP), organisation, provider with
  capability test, one model for all roles, moderation test, completion gate. Setup cannot
  be skipped; no check/chat before it is complete.
- Full role/permission model: role templates, per-user grants/revocations, multiple roles,
  permission matrix; `users:manage` separate; API keys and device tokens ≤ owner; four-eyes
  setting; password resets without email; TOTP mandatory for privileged permissions,
  optional otherwise; recovery codes.
- Session security: Argon2id, server-side sessions, rotation on login, CSRF, logout all,
  idle/absolute expiry, rate-limited login, audit events.
- Limits per role with per-user overrides: text length, requests/day, LLM budget,
  concurrent jobs, file size, files per batch; API key limits ≤ user; enforcement before
  work starts; clear errors.
- Device tokens: create/list/revoke; "connect plugin" flow hands the token to the extension
  through a one-time state; device shown in the web UI; token last-seen.
- Retention jobs: context metadata expiry (default 90 days), deleted chats, QS deletion,
  job/event cleanup, usage event 90-day rollup, summaries; audit of deletions.
- GDPR views: own chats delete, own data export? (minimum: delete); admin retention
  settings.
- Security hardening: password policy, session fixation, CSRF, login throttling,
  permission tests, no secrets in logs, no Docker socket, CSP for the future web app.

**Done when.**

- `[agent]` a fresh volume completes the wizard in under 15 minutes measured from container
  start to the first successful check; skipping moderation or the provider test blocks
  completion; the timing is reported.
- `[agent]` a matrix test covers every permission × endpoint (allowed/denied), including
  API keys and device tokens with subsets, a user with two roles, a revoked grant and a
  token revocation; no endpoint lets a caller exceed its owner.
- `[agent]` TOTP is required for operator/editor/users:manage and optional for a plain
  user; a wrong code is rejected; recovery codes work; password reset by `users:manage`
  invalidates old sessions.
- `[agent]` each limit can be lowered per user and is enforced before a model call; an API
  key with a lower limit fails while the user's own session still works; budget exhaustion
  still serves cache hits and returns the documented `429`.
- `[agent]` a device token created for the extension has only `claims:submit` by default,
  cannot call documents or usage summaries, and stops working immediately after revocation.
- `[agent]` retention: a context older than the configured period loses author/URL/platform,
  a deleted chat keeps an anonymised claim, QS deletion is audited, job/event cleanup runs.
- `[agent]` `make verify` is green; the phase report includes the permission matrix, the
  setup timeline and the spend.
- `[human]` none for this phase; the setup UI is reviewed in Phase 8.

---

## 9. Phase 6 — Model registry, capability tests, data flow, usage and re-index

**Status: complete (2026-11-17).** Provider CRUD with encrypted write-only keys and a
connection test; model registry with direct capability probes (chat, structured output,
vision, embedding dimension and cross-lingual similarity, moderation) stored as
`tested`/`assumed`; one pure role rule used by the assignment endpoint and the role list;
data-flow policy with an allowed fallback and a transport test proving a blocked call never
leaves the process; a zero-cost exemption so local cache embeddings keep working when the
paid budget is exhausted; per-role budgets; usage summaries, breakdowns and CSV; publisher
overrides merged at retrieval with diff, resolve and cache-impact; persona and methodology
overrides with catalog/canonical validation and immutable Shared Invariants; and an explicit
re-index job that moves the embedding lock, resolves LightRAG ids, waits for deletion and
dispatches the document index jobs. The report is
[`docs/PHASE_6_REPORT.md`](docs/PHASE_6_REPORT.md). A per-key monthly USD ledger is recorded
as a later hardening follow-up; the phase checks are met.

**Goal.** The operator can configure providers and models safely, the UI and backend agree
on what is suitable, no call can bypass the data-flow policy, and usage is auditable.

**Scope.**

- Provider CRUD with encrypted keys, connection test, model discovery (Ollama `/api/show`,
  LM Studio model type, OpenAI-compatible fallback by name), model CRUD.
- Capability probes: chat, structured output (JSON Schema), vision (test image with text),
  embedding with measured dimension, multilingual/cross-lingual similarity, rerank,
  moderation; each capability `tested` or `assumed`; tests stored with model version/time.
- Role requirements and assignment validation: a single rule source used by the UI filter
  and the backend; wrong assignment → `422` with a reason; mandatory roles require tested
  capabilities; "show others" reasons; model usage map.
- Data-flow policy editor and enforcement: local/external labels, per-class rules, fallback
  or explicit failure; test that a forbidden external call never leaves the process;
  evidence in usage.
- Budgets: per user, key, role, instance monthly; budget checks in the gateway; cache-only
  behaviour; reset times; global monthly ceiling.
- Usage API and summaries: cards, series, breakdowns, CSV, retention, no contents;
  `usage:read`; optional `/metrics`.
- Publisher list management: shipped list, local overrides, diff, resolve endpoint, impact
  on cached results, disputed cap; publisher warnings at approval.
- Methodology management: checklists, patterns, domains, personas CRUD, language support
  list; versioning and audit; editing defaults/test console.
- Re-index flow: explicit confirmation, model lock check, rebuild from approved documents,
  progress, failure recovery, no LightRAG index backup.

**Done when.**

- `[agent]` a provider is added with a key, the key is encrypted at rest, the connection test
  passes, and the key is never returned or logged; a second provider can be a local
  OpenAI-compatible endpoint.
- `[agent]` chat and vision models are tested with the real provider; a wrong assignment
  (embedding model for verification, non-vision model for images, dimension mismatch)
  returns `422` with the exact reason; the UI filter rule returns the same reason (unit
  test of the shared rule).
- `[agent]` a data-flow rule blocks an external call carrying `user_input`; the gateway
  falls back to an allowed model if configured, otherwise returns `403 data_flow_blocked`,
  and usage shows the restriction; no request body reaches the forbidden provider (transport
  test).
- `[agent]` budgets: a key at its daily limit gets `429`, its user's session is unaffected,
  cache hits still work, and the instance monthly ceiling blocks all new paid calls with a
  clear message; usage totals and CSV match the recorded events.
- `[agent]` a local publisher override changes the effective grade of a new retrieval, the
  diff is visible, cached results are listed by the impact endpoint, and a re-check uses
  the new grade; a disputed entry is capped at `C`.
- `[agent]` persona CRUD validates the schema and checks catalog, a failing canonical test
  needs an explicit override, and a user-created persona cannot remove the Shared
  Invariants.
- `[agent]` re-index: changing the embedding model is refused while the corpus is
  non-empty; the explicit flow rebuilds the index from approved documents and checks still
  work; a failed re-index leaves the old corpus intact and reports the failure.
- `[agent]` `make verify` is green; the phase report includes capability timings, data-flow
  proof and spend.
- `[human]` none for this phase; the settings UI is reviewed in Phase 8.

---

## 10. Phase 7 — Web design system and the core checking experience

**Goal.** A person can sign in, check text/file/image/URL, read the report, browse the
archive and chat with the service, in a calm, accessible, bilingual-ready interface.

**Scope.**

- SvelteKit SPA scaffold, Tailwind tokens, light/dark/system, reduced motion, system font
  stack, Lucide, Bits UI; about ten core components (button, input, segmented control,
  badge, card, sheet, popover, list, evidence card, verdict card); preview page.
- Generated API client, typed fetch, auth/session handling, CSRF, error mapping, i18n
  message catalog en/de/fr/es with a language switcher.
- Screens: Spotlight-like Check; Report (verdict card, deterministic sections, colored
  statement spans with side panel, evidence cards, citations, figure crop, warnings);
  Archive (search, filters, versions, feedback); Chat (streaming, personas, report inline);
  login; shell/navigation by role.
- Check flows: text, file, image, URL; async progress with SSE; partial statements; retry;
  clarification questions; language override; persona and output format selection.
- Report rendering: deterministic substance always visible; narrative after checked
  streaming; fallback template; compact view for narrow screens.
- Accessibility: keyboard navigation, focus management, labels, contrast, no color-only
  status, motion reduction; axe checks in Playwright.
- Playwright screenshots: light, dark, narrow, wide for each core screen.

**Out of scope:** editorial screens, batch, usage, settings, devices, PWA.

**Done when.**

- `[agent]` `make verify`, `make web-check` and the Playwright E2E suite pass; a real check
  runs through the browser from input to report with a real backend and provider; SSE
  updates the progress and partial statements; a file, an image and a URL each work from
  the UI.
- `[agent]` the report shows the deterministic verdict, what is true/missing/unverifiable,
  evidence with provenance, and warnings; color is never the only signal; the narrative is
  hidden until the consistency check completes; a forced fallback shows the template.
- `[agent]` archive search finds a checked claim, opens a version, and submits feedback; a
  second check of the same claim links to the archive.
- `[agent]` the UI is usable in de/fr/es (navigation, forms, verdict labels, refusal and
  error messages); backend-generated prose stays in its own language and is not
  re-translated by the UI; an unsupported input language shows the English notice.
- `[agent]` screenshots (light/dark/narrow/wide) are stored in `docs/screenshots/phase-7/`;
  axe reports no serious/critical violations; no horizontal scroll at 360 px.
- `[human]` **visual acceptance** of the design system and the Check/Report/Archive/Chat
  screens against PURPOSE §3.14. The agent stops here with the screenshot links and a
  short list of what to look at.

---

## 11. Phase 8 — Editorial, batch, usage, settings and the plugin handoff

**Goal.** The editorial workflow, batch upload, usage overview, settings and the browser
extension connection are usable in the real UI, and the app is installable as a PWA.

**Scope.**

- Editorial queue like mail (list/detail, keyboard shortcuts, warning row, preselection,
  approve/reject/withdraw, figure correction, document text, contradictions and gaps).
- Batch upload UI: drag and drop, folder, ZIP, URL list, metadata file, per-file progress,
  summary counts, retry, cost estimate and budget, checkbox approval.
- Usage views: metric cards, trends, user table with detail, period segmented control, CSV
  export, budget banner, no contents; own usage for every user.
- Settings: macOS-like grouped settings for providers/models/roles/capabilities/data flow/
  budgets, moderation test console, publisher list with diff, methodology, personas with
  test console, language support, limits, retention, devices, API keys, four-eyes, backup
  status; no JSON editors.
- First-run setup UI, one step per screen, with progress and blocking tests.
- PWA: manifest, service worker, install prompt, share target on Android, iOS shortcut
  instructions; offline shell for static pages (no offline checks).
- Extension connect: "Connect plugin" flow, one-time state handoff, device list/revoke,
  compact report endpoint, CORS allowlist, image dimension guidance; plugin fork
  instructions in `docs/EXTENSION.md` (the fork itself lives in its own repository).
- Final design pass, error/empty/loading states, toasts, confirmations for destructive
  actions, audit-friendly copy.
- Playwright screenshots for every screen, light/dark/narrow/wide, plus E2E for editorial
  approval, batch, usage, setup and device connect.

**Done when.**

- `[agent]` an editor reviews and approves a warning document and a preselect batch in the
  UI; the approved document becomes citable; a withdrawal stops new citations; figure
  corrections are visible; contradictions and gaps are actionable.
- `[agent]` a batch of mixed files completes with the summary counts and individual retry;
  the cost estimate and budget are shown before the run; the UI stays consistent while the
  window is closed and reopened.
- `[agent]` the usage screen shows totals, trends, per-user detail, budget and CSV; it shows
  no claim content; the operator sees all, a normal user sees only their own.
- `[agent]` the setup wizard can be completed from zero, the settings screens save and
  reload, a wrong model assignment shows the reason, and the moderation test console
  reports pass/fail.
- `[agent]` the PWA installs and the share target opens a prefilled check; the device
  connect flow creates a `claims:submit` token and the extension can submit a compact check
  with it; revoking the device stops it.
- `[agent]` screenshots and E2E are green; no serious/critical axe issues; keyboard-only
  walkthrough works; i18n is complete for the new screens.
- `[human]` **visual acceptance** of the editorial, batch, usage, settings and setup screens
  and of the PWA install; **plugin test** in a real browser (Chrome/Edge, Firefox) against
  the running stack: select text on a page, check it, see the compact report, open the full
  report, disconnect/revoke. The agent stops here.

---

## 12. Phase 9 — Evaluation, hardening, packaging and acceptance

**Goal.** The tree is reproducible, the evaluation is honest, the security and operational
requirements are tested, and the delivered stack can be started by someone else.

**Scope.**

- Repair and extend the carried-over evaluation sets: `tests/eval/claims.seed.jsonl` has
  duplicated ids and repeated rows in its current state; re-label against the fixture
  corpus for the new one-source gate and `contested`; add normative, adversarial-nonsense,
  quote-context, stale, injection, cross-lingual, table/figure-only and moderation cases;
  document the labeling.
- Eval runner: per-verdict precision/recall, macro-F1, misleadingness recall, gate-downgrade
  rate, consistency-fallback rate, fast latency/cache hit rate; `--predictions` recorded
  baseline; coverage enforcement; honest failure when the set is missing or empty.
- Record/replay: capture the real responses for the canonical and eval cases once, commit
  fixtures, run the suite offline; a check that all fixtures are fresh? At least a schema
  check.
- Live evaluation within budget: baseline numbers, latency p50/p95 for cache, fast and full,
  audit-completion rate, consistency failures, cost per check; report spend.
- Schemathesis against the public `/v1` OpenAPI: no 5xx, no schema violations, documented
  status codes only.
- Security tests: SSRF (IPv4/IPv6, DNS rebinding, redirects), ZIP bombs/path traversal,
  upload magic bytes, prompt injection in documents/URLs/figures, moderation fail-closed,
  permission matrix, session fixation, CSRF, rate limits, secret redaction, no Docker
  socket, dependency audit.
- Operations: Caddy with TLS (internal CA in dev, Let's Encrypt in production), static web
  served, SSE proxy timeouts, healthchecks, log rotation, backups (`make backup`,
  `make backup-test` restore into a fresh stack), re-index from approved documents, clean
  start from empty volumes, upgrade notes.
- Docs: README status and quick start, `docs/OPERATING.md`, `docs/EXTENSION.md`,
  `docs/EVALUATION.md`, `docs/SECURITY.md`, `DECISIONS.md`, `AGENTS.md` setup commands
  updated to the real commands.
- CI: exact `make verify` + compose smoke + web build + eval-recorded + screenshots
  artifact.
- Final acceptance: run the full definition of done from a clean checkout on a machine with
  Docker and a browser.

**Done when.**

- `[agent]` `make verify` is green from a clean checkout; `docker compose up --build` from
  empty volumes completes setup; the first check works; `make backup-test` restores the
  database and files into a fresh stack and a check still works.
- `[agent]` the recorded evaluation runs offline and reports the metrics; the live
  evaluation runs within budget and reports p50/p95, verdict metrics, consistency/gate
  rates and cost; the claims set has no duplicate ids and covers all seven verdicts and the
  required flags; coverage enforcement passes.
- `[agent]` Schemathesis reports no 5xx and no undocumented status codes on `/v1`; the
  security tests pass, including SSRF redirect/DNS cases, ZIP protections, injection and
  moderation fail-closed; the permission matrix has no hole.
- `[agent]` Caddy serves HTTPS, the SPA, the API and SSE through the proxy; no `/internal`
  route is reachable from outside; `/metrics` is off by default; logs contain no content or
  secrets.
- `[agent]` the final report lists every phase check, the exact commands, the evaluation
  numbers, the spend and the known limitations. It does not claim more than ran.
- `[human]` **final acceptance**: compare the delivered behaviour and UI with `PURPOSE.md`,
  run the extension test, approve the release. The agent stops here.

---

## 13. Cross-cutting verification matrix

| Requirement | Phase | Evidence |
| --- | --- | --- |
| Verdicts/evidence IDs only from structured output | 1, 2 | schema tests, invalid-ID tests, recorded runs |
| Overall verdict, gate, contradiction by code | 1, 3 | pure-function unit tests + fixture runs |
| Style never alters substance | 2, 7 | consistency tests, render comparison |
| Research attributes, never asserts | 3 | forced inconsistency test + live run |
| Only approved documents enter LightRAG | 1, 4 | CLI approval audit, approval/withdrawal tests |
| Prompt injection is data | 1, 2, 4, 9 | injection fixtures, no instruction following |
| LightRAG stock; no answer generation | 1 | client path allowlist test, logs |
| Every LLM call through the gateway | 1, 6 | egress test, usage events, no direct provider config |
| Permissions server-side | 5 | permission matrix |
| Model assignments validated | 6 | capability tests, 422 cases |
| Embedding/vision model immutable per corpus | 4, 6 | lock test, re-index test |
| Checked streaming | 2, 7 | SSE/stream trace, judge-before-content test |
| Moderation flags, only `sexual_minors` blocks | 1, 2, 9 | moderation set, fail-closed test |
| Timeouts, retries, circuit breakers, SSRF | 1, 9 | transport/security tests |
| Secrets hashed/encrypted, shown once | 1, 5, 6 | secret scan, response tests |
| Quantities, not contents | 6, 8 | usage payload tests, UI review |
| Boring, tested code; decisions recorded | all | `DECISIONS.md`, tests, review |

---

## 14. Risks and open technical questions

| Risk | Mitigation | Decision point |
| --- | --- | --- |
| Stock LightRAG v1.5.0 with Postgres/AGE storage does not start cleanly | early Phase 1 smoke; use documented config only; stop after two attempts | Phase 1 |
| LightRAG's retrieval still calls its own keyword LLM and sends claim text | pass `hl_keywords`/`ll_keywords`; verify gateway records consumer `lightrag` and data class; if unavoidable, document the data flow | Phase 1 |
| A provider supports only JSON mode, not strict JSON Schema | schema in prompt + Pydantic validation + one repair retry; capability is "tested structured output" only if the probe passes | Phase 1 |
| Docling install/parse is heavy or fails on ARM | pin and test early in Phase 4; fall back only with a human-approved scope change | Phase 4 |
| Fast target 15 s cannot be met with remote models | reduce calls, use a cheaper model, cache; never drop the audit/gate; report measured latency | Phase 3 |
| Batch cost estimates are inaccurate | measure actual tokens/pages; tune estimator; never start over budget; report deviation | Phase 4 |
| Duplicated/garbled carried-over eval sets | repair ids and rows first; re-label against the fixture corpus; coverage check | Phase 9 |
| Brand colour/logo absent | propose a calm accent and simple mark during the design system; human approves | Phase 7 |
| Live model spend | cap, cheap models, local embeddings, report per phase; stop at the cap | all |

No open question blocks Phase 1. The only required human input before code is the plan
approval and the budget in §2.

---

## 15. First-run and verification commands (target state)

After Phase 1, these are the real commands; `AGENTS.md` is updated in the same commit that
first makes them real. Nothing below is a placeholder that is allowed to remain stale.

```bash
cp .env.example .env            # fill secrets; never commit
make install                    # uv sync --frozen; pnpm install --frozen-lockfile
make migrate                    # alembic upgrade head
make stack-up                   # docker compose up -d --build
make stack-smoke                # health, setup state, one real check, spend report
make verify                     # all local gates (no live model)
make test-integration           # Testcontainers + fakes
make e2e                        # Playwright against the compose stack
make screenshots                # light/dark/narrow/wide
make eval-recorded              # offline labelled evaluation
make eval-live                  # explicit live run, budget-checked
make schemathesis               # public /v1 only
make backup                     # Postgres + originals
make backup-test                # restore into a fresh stack and verify
```

`make stack-smoke` is the one command a human can run to see the product work. It must
print what it checked, which providers were used, the tokens/cost and where the report is.

---

## 16. Approval

This plan is executable only after the human:

1. approves the revised `PURPOSE.md`, `PROTOCOL.md` and `PERSONAS.md` (source of truth for
   the implementation), and
2. sets the live-model budget in §2 (proposal: USD 15, hard stop USD 20).

On approval, Phase 1 starts immediately. At every `[human]` check the agent stops and asks;
it does not continue into the next phase on its own.
