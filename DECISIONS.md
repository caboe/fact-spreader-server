# Decisions

One short entry per non-obvious decision: what, why, alternatives rejected. Decisions, not
bug diaries. A new runtime dependency or a pinned image bump gets an entry here.

---

## D1 — Postgres-backed job queue, no second broker

**What:** pipeline jobs live in the `jobs` table and are claimed with
`SELECT … FOR UPDATE SKIP LOCKED`; SSE in Phase 2 reads durable state from Postgres.

**Why:** the job must survive backend and worker restarts, partial results must be durable,
and reconnecting clients must be able to rebuild the view. Postgres is already the source
of truth, so the queue adds no new failure mode.

**Rejected:** Redis Streams/arq (another durable store and a second thing to back up),
Celery (heavy, sync-first), a separate queue service (not justified at this scale).

## D2 — Stock LightRAG v1.5.0 pinned, Postgres all-in-one storage

**What:** `ghcr.io/hkuds/lightrag:v1.5.0`, configured only through documented environment
variables; `POST /query/data` for retrieval, never `/query` or `/query/stream`.

**Why:** hard invariant 7. The version is tested with the compose stack; `latest` is
forbidden. Postgres is already deployed for the app, so pgvector + AGE avoids a second
storage engine.

**Rejected:** a forked LightRAG (maintenance and drift), LightRAG's answer generation (it
would bypass our gate and citation rules), a separate vector database (not needed).

## D3 — Internal LLM gateway inside the backend

**What:** `/internal/llm/v1` is an OpenAI-compatible chat/embeddings/vision proxy with a
stable alias per role, one internal key per consumer, budget checks and usage events.
LightRAG points at it with `fs-extract` and `fs-embedding`.

**Why:** hard invariant 8; data-flow policy, budgets and usage must cover LightRAG's calls
too. A separate gateway service would add a deployment unit without adding a control we do
not already own.

**Rejected:** LiteLLM (a second budget/permission system, contrary to the redesign), direct
provider calls (bypasses usage and policy), a sidecar (same reason as separate service).

## D4 — Local multilingual embeddings via Ollama in this environment

**What:** the gateway resolves `fs-embedding` to `bge-m3` via Ollama's OpenAI-compatible
`/v1/embeddings`, dimension 1024. Production may point the same alias at any compatible
embedding provider.

**Why:** the embedding model must be multilingual and free of per-call cost for ingestion;
the agent environment has the model locally. The corpus locks the model and dimension.

**Rejected:** OpenAI embeddings (cost per ingestion, unnecessary), English-only embeddings
(violates cross-lingual retrieval), hashing vectors (not semantic, useless for LightRAG).

## D5 — Server-side sessions and hashed credentials

**What:** opaque session tokens stored hashed in Postgres, Argon2id passwords, API keys and
device tokens SHA-256 hashed and shown once. No JWTs. Internal gateway key from deployment
configuration.

**Why:** revocation is immediate; no signing-key rotation footgun; hard invariant 15.

**Rejected:** JWT access tokens (revocation needs a denylist anyway), bcrypt (Argon2id is
the current default), plaintext provider keys in `.env` at runtime (the bootstrap key is
encrypted in the database and the `.env` value is only used once).

## D6 — Fixture approval CLI in Phase 1

**What:** `python -m app.cli seed-fixtures --approve` creates a real approval record for the
synthetic fixtures and indexes them. It is the only Phase 1 corpus path and is replaced by
the editorial API/UI in Phase 4.

**Why:** Phase 1 needs real LightRAG content to prove the slice, but automatic approval is
forbidden. An explicit CLI flag with a recorded approver is a human decision, not an
automatic one.

**Rejected:** seeding on startup (automatic approval), bypassing the approval record
(loses provenance and would violate invariant 5), an in-memory fake corpus (not a real
slice).

## D7 — JSONB for the nested result payload in Phase 1

**What:** `results.statements`, `evidence`, `warnings` etc. are Postgres JSONB, validated by
Pydantic at write and read; document/passage/usage/audit rows are relational.

**Why:** the result is an immutable, versioned document; normalising every citation and
section before the UI exists adds migrations without a query need. Archive search and
semantic cache are added in Phase 3 with the queries that need them.

**Rejected:** a table per section (premature), a document store (another system), storing
only rendered text (violates substance/style separation).

## D8 — Deterministic fakes in the regular suite, live smoke separately

**What:** unit and integration tests inject a fake LLM client and a fake LightRAG client.
The real stack is exercised by `make stack-smoke` and `make eval-live` only.

**Why:** no network calls or live spend in the regular suite (AGENTS.md); the fake boundary
is the same interface the gateway uses, so the wiring is still tested.

**Rejected:** recorded provider responses in Phase 1 (not captured yet; Phase 9 adds the
record/replay fixtures), monkeypatching HTTP internals (brittle, tests less than the
contract).

## D9 — Pinned Postgres image built from source extensions

**What:** `deploy/postgres/Dockerfile` builds Postgres 16.6 with pgvector 0.8.0 and Apache
AGE 1.5.0-rc0 for PG16, and initialises the `app` and `lightrag` databases.

**Why:** LightRAG's Postgres storage needs both extensions; a maintained prebuilt image was
not available with the required pins. The image is rebuilt deliberately, not pulled from
`latest`.

**Rejected:** runtime extension installation (slow, non-reproducible), a separate graph
database (LightRAG's Postgres backend is the documented all-in-one path).

## D10 — No Caddy in Phase 1

**What:** Phase 1 exposes the backend on `127.0.0.1:8000` and LightRAG on
`127.0.0.1:9621`; Caddy and HTTPS arrive in Phase 9 with the web app.

**Why:** the slice is an API proof; adding TLS before there is a browser client adds a
certificate failure mode to the first vertical slice. No non-loopback exposure.

## D11 — Deterministic sexual-minors floor in front of the classifier

**What:** a narrow regex guard blocks explicit sexual content involving a minor before the
configured LLM classifier runs. It is not configurable and is recorded as
`hard_floor:sexual_minors`.

**Why:** hard invariant 13 makes this category an absolute block. A provider-side refusal or
a cautious classifier returned `allow` for a clearly explicit test string during Phase 1;
relying on the model alone would make the absolute rule probabilistic. The guard is narrow
so that legitimate discussion of child abuse and prevention remains checkable.

**Rejected:** relying only on the LLM classifier (observed false negative), keyword-blocking
every mention of minors plus abuse (over-blocks legitimate claims), making the floor an
operator setting (violates the invariant).

## D12 — Synthetic fixture documents get a document-level quality override

**What:** during `seed-fixtures --approve`, a document whose publisher starts with
`Example ` (the synthetic corpus deliberately avoids impersonating real institutions) gets
grade `A` with `source_quality_basis.source = document_override` and entry
`fixture-corpus`.

**Why:** the shipped publisher list correctly refuses to grade non-existent publishers.
Without an override, the fixture corpus could not exercise the gate or the canonical
misleading case at the minimum quality `B`. The override is recorded on the document, is
visible in every provenance, and does not touch the shipped list.

**Rejected:** adding fake publishers to `methodology/publishers.json` (pollutes production
data), lowering the gate for the whole instance (weakens the invariant), changing the
fixture publishers to real institutions (implies a false attribution even with the FIXTURE
banner).

## D13 — Verification output budget and invalid-output retry policy

**What:** the verification/audit call gets an 8,000-token output budget. A model output
that twice fails schema/evidence-id validation fails the job after the client's one repair
attempt; the worker does not retry that class of failure.

**Why:** the first live run used 3,500 tokens, all consumed by the model's reasoning, and
returned an empty content string. Retrying it three times produced no new information and
cost tokens. The budget leaves room for the structured JSON; the client already makes one
repair attempt, so a further worker retry is noise for a non-transient failure.

**Rejected:** silently treating empty output as `insufficient_evidence` (hides a provider
failure), disabling reasoning (not a documented provider switch), using a larger premium
model for every check (cost).

## D14 — Phase 1 rejects unavailable features explicitly

**What:** file, URL and image input, fast/sync mode, persona rendering and conversation
context return `422` with a specific code in Phase 1 instead of being accepted and silently
ignored.

**Why:** a client that sends context or a fast flag must not receive a result that looks as
if the feature was used. The Phase 2 work is visible in the API contract and in the plan.

**Rejected:** accepting and ignoring unsupported fields (silent behaviour change), returning
`501` for the whole endpoint (blocks the working slice), implementing a half-parser for
files without the shared ingestion path.
