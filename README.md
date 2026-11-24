# Fact Spreader — server

A fact-check and research service over a curated, editorially approved knowledge base.
It verifies the factual core of a claim, audits what the claim leaves out and how it
frames it, and returns a structured verdict with citations. The defining case is the
**formally true but misleading** claim. Browser extension:
[fact-spreaders/fact-spreader](https://github.com/fact-spreaders/fact-spreader).

## Status

**Phases 1–9 complete; final acceptance recorded 2026-11-18 (extension test deferred until the extension exists).** The stack runs end to end:
check, report, archive, chat, editorial review, batch submission, operator settings, PWA
and the device-token connect flow. `make verify` is green and the Playwright suite passed
27 tests against the live stack (2 optional skips). Live evidence and spend are in the
phase reports:

- [`docs/PHASE_1_REPORT.md`](docs/PHASE_1_REPORT.md) — vertical slice, gateway, gate
- [`docs/PHASE_2_REPORT.md`](docs/PHASE_2_REPORT.md) — personas, checked streaming
- [`docs/PHASE_3_REPORT.md`](docs/PHASE_3_REPORT.md) — research, fast mode, latency
- [`docs/PHASE_4_REPORT.md`](docs/PHASE_4_REPORT.md) — documents, review, batch
- [`docs/PHASE_5_REPORT.md`](docs/PHASE_5_REPORT.md) — setup, TOTP, permissions, retention
- [`docs/PHASE_6_REPORT.md`](docs/PHASE_6_REPORT.md) — registry, roles, budgets, overrides
- [`docs/PHASE_7_REPORT.md`](docs/PHASE_7_REPORT.md) — SPA, i18n, screenshots
- [`docs/PHASE_8_REPORT.md`](docs/PHASE_8_REPORT.md) — editorial, batch UI, settings, PWA
- [`docs/PHASE_9_REPORT.md`](docs/PHASE_9_REPORT.md) — evaluation, hardening, edge, acceptance

The specification is frozen in [`PURPOSE.md`](PURPOSE.md), [`PROTOCOL.md`](PROTOCOL.md) and
[`PERSONAS.md`](PERSONAS.md); [`IMPLEMENT.md`](IMPLEMENT.md) is the approved phase plan and
[`DECISIONS.md`](DECISIONS.md) records non-obvious choices. Phase 9 covers the evaluation,
security hardening, Caddy edge, backups and the recorded acceptance.

## Quick start

```bash
cp .env.example .env            # fill secrets; never commit
make install                    # uv + pnpm, locked
make stack-up                   # Postgres, Redis, backend, workers, LightRAG, Caddy
```

Open <https://localhost:8443> and complete the wizard with `SETUP_TOKEN` from `.env`
(admin, TOTP, organisation, provider, models, moderation). `make bootstrap` is the
automation path. Then submit a document in `/submit`, approve it in `/editorial` and run
a check on `/`.

```bash
make verify            # lint, types, unit + integration, migrations, OpenAPI, compose, web, site
make site-check        # handbook typecheck, build, link check, public composition
make stack-smoke       # one real canonical check, no-evidence case and moderation block
make eval-recorded     # offline labelled evaluation
make backup            # database dump
make backup-test       # restore into a throwaway stack and check
```

Operating details are in [`docs/OPERATING.md`](docs/OPERATING.md), security in
[`docs/SECURITY.md`](docs/SECURITY.md), the extension connection in
[`docs/EXTENSION.md`](docs/EXTENSION.md) and the evaluation in
[`docs/EVALUATION.md`](docs/EVALUATION.md). The user handbook is in
[`handbook/`](handbook/README.md); [`site/`](site/) builds it as a static site, and every
instance serves the same build at `/handbook/`.

Phase 1 is a vertical slice: a text claim goes through the public API, a Postgres-backed
worker, stock LightRAG, the internal LLM gateway, a real model, the pure gate, and comes
back as a deterministic report with citations. It also proves moderation fail-closed and
the sexual-minors block.

| Area | Phase 1 state |
| --- | --- |
| Check API | text input, async job, `GET` result, minimal SSE (`state`, `done`), idempotency |
| Pipeline | extraction with spans, retrieval, verification/audit, gate, contradiction/recency, overall verdict |
| Evidence | approved documents only, provenance, source grades, `contested` model |
| Moderation | configured classifier, deterministic sexual-minors floor, fail closed |
| LLM gateway | internal OpenAI-compatible chat/embeddings proxy, aliases, budget, usage, embedding lock |
| Languages | en/de/fr/es deterministic substance; unsupported input falls back to English |
| Operations | pinned Postgres+pgvector+AGE, Redis, stock LightRAG v1.5.0, health/readiness |
| Tests | 63 unit, 26 integration, migration up/down/up, OpenAPI drift, compose checks |

Phase 2 so far adds three runtime personas (analyst, mediator, straight-talker), the
deterministic checks plus a consistency judge with one re-render and a template fallback,
output moderation, `GET /v1/models` with the persona list, `POST /v1/chat/completions` with
checked streaming, SSRF-guarded URL input (HTML/PDF readers), multipart file input
(PDF/DOCX/HTML/Markdown/text), image input through the mandatory vision path, a read-only
claim archive with cursor pagination, durable statement-level SSE events with
`Last-Event-ID` replay and queued-job cancellation. A live OpenAI-compatible canonical run
passed the consistency check on the first attempt; a live streaming run delivered the
result in the first chunk and narrative deltas only afterwards; a live screenshot check
extracted the text and returned `true_but_misleading` with the image-authenticity warning.

Phase 2 also includes revocable device tokens with a permission subset
(`claims:submit` by default, shown once, hashed at rest), persistent archive feedback,
conversation context with a code-side turn heuristic, and labelled translations of
non-response-language evidence. The full live persona × language matrix passed: all twelve
runs returned a persona narrative with the consistency check passed on the first attempt
and no warnings. Later phases add fast mode, the editorial pipeline and the UI.

Phase 3 adds research: `POST /v1/search` returns approved documents, passages and archive
hits, plus an optional attributed summary. Code checks every citation, an independent
`fs-verify` judge confirms support, and a failed or timed-out summary is withheld. A claim
with an open confounder triggers one targeted retrieval; the pure gate still downgrades a
proposed `true` to `insufficient_evidence` with `audit_incomplete`. Contradiction records,
the staleness downgrade and corpus-gap aggregation are in place. Fast mode serves a
pgvector semantic-cache hit in 1.3–1.7 s and a cold preliminary in 9.6 s while the full
check runs as a new version; the archive lists only the newest version and keeps the whole
chain in its detail. Manual re-checks and QS soft deletion are implemented. Automatic
re-checks on corpus changes and the Phase 3 live acceptance run are still open.

## Quick start (development)

Requires Docker, Python 3.12 with [`uv`](https://docs.astral.sh/uv/), and a local
OpenAI-compatible embedding model for this environment (`bge-m3` on host Ollama) or any
compatible embedding endpoint. Copy `.env.example` to `.env` and fill the secrets and
provider values; `.env` is gitignored and must never be committed.

```bash
make install
make stack-up          # builds Postgres and the backend, starts the pinned stack
make bootstrap         # creates the instance, admin, providers/models and a smoke API key
make seed-fixtures     # explicitly approves and indexes the synthetic crime fixtures
make stack-smoke       # live check of the canonical case, no-evidence case and block case
make verify            # unit + integration, migrations, OpenAPI drift, compose checks
```

The stack is bound to loopback: API `http://127.0.0.1:8000`, LightRAG
`http://127.0.0.1:9621`, Postgres `5432`, Redis `6379`. Caddy/TLS and the web app arrive in
Phase 9 and Phase 7 respectively.

## Layout

| Path | What |
| --- | --- |
| [`PURPOSE.md`](PURPOSE.md), [`PROTOCOL.md`](PROTOCOL.md), [`PERSONAS.md`](PERSONAS.md) | Requirements, normative wire contracts, runtime persona configuration |
| [`IMPLEMENT.md`](IMPLEMENT.md), [`DECISIONS.md`](DECISIONS.md) | Phase plan and decision log |
| `backend/` | FastAPI app, worker, Alembic, unit/integration tests |
| `deploy/` | Pinned Postgres image and static stock-LightRAG configuration |
| `methodology/` | Publisher grades, confounder checklists, argument patterns |
| `handbook/` | User and operator handbook in Markdown (CC BY-SA 4.0); source of the website |
| `site/` | Astro + Starlight build for the public site and the instance's `/handbook/` |
| `tests/eval/`, `tests/fixtures/corpus/` | Carried-over evaluation sets and the synthetic CI corpus |

## Licences

* Code: [GNU AGPL-3.0-or-later](LICENSE).
* Methodology data, personas, the handbook, evaluation sets and the fixture corpus
  (`methodology/`, `PERSONAS.md`, `handbook/`, `tests/eval/`, `tests/fixtures/corpus/`):
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
* Contributions are accepted under the
  [Developer Certificate of Origin](https://developercertificate.org/): sign off your
  commits (`git commit -s`).
