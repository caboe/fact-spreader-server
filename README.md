# Fact Spreader — server

A fact-check and research service over a curated, editorially approved knowledge base.
It verifies the factual core of a claim, audits what the claim leaves out and how it
frames it, and returns a structured verdict with citations. The defining case is the
**formally true but misleading** claim. Browser extension:
[fact-spreaders/fact-spreader](https://github.com/fact-spreaders/fact-spreader).

## Status

**Phase 1 complete; Phase 2 in progress (2026-11-17).** The specs were revised for the v1
scope on 2026-11-16 using [`docs/REDESIGN_NOTES_DE.md`](docs/REDESIGN_NOTES_DE.md) as the
decision log; [`IMPLEMENT.md`](IMPLEMENT.md) is the approved plan and
[`DECISIONS.md`](DECISIONS.md) records the non-obvious implementation choices. The Phase 1
evidence, including live-model spend, is in
[`docs/PHASE_1_REPORT.md`](docs/PHASE_1_REPORT.md). Phase 2 has started with the persona
renderer and the OpenAI-compatible checked-streaming surface; file/URL/image input,
statement-level SSE, the full archive and the rest of Phase 2 remain open.

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
| Tests | 59 unit, 23 integration, migration up/down/up, OpenAPI drift, compose checks |

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
non-response-language evidence. The remaining Phase 2 item is the full live persona ×
language matrix; the mechanical checks are covered for en/de/fr/es. Later phases add
research, fast mode, the editorial pipeline and the UI. A first Phase 3 slice adds
research: `POST /v1/search` returns approved documents, passages and archive hits, plus an
optional attributed summary whose sentences are citation-checked deterministically. The
summary judge and the fast mode are still open.

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
| `tests/eval/`, `tests/fixtures/corpus/` | Carried-over evaluation sets and the synthetic CI corpus |

## Licences

* Code: [GNU AGPL-3.0-or-later](LICENSE).
* Methodology data, personas, evaluation sets and the fixture corpus
  (`methodology/`, `PERSONAS.md`, `tests/eval/`, `tests/fixtures/corpus/`):
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
* Contributions are accepted under the
  [Developer Certificate of Origin](https://developercertificate.org/): sign off your
  commits (`git commit -s`).
