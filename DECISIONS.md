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

## D15 — Persona renderings are released only after two independent checks

**What:** every narrative passes deterministic checks (citation IDs, second-person rules
for impersonal personas, question limits, bottom-line and verdict-label rules, unbacked
pattern names) and a judge call. The free-text judge `issues` list is used only when the
judge reports `passed = false`; the explicit violation lists still fail a narrative that the
judge marked passed. A failed first attempt is re-rendered once; a second failure uses the
deterministic template and records `consistency_fallback`. The output is then moderated;
a hit replaces it with the template and records `output_moderation_replaced`.

**Why:** hard invariant 3 and 12. The first live judge run returned advisory issues with
`passed = true`; treating those as failures made every persona fall back. The explicit
violation fields are the contract; free-text advice is not a failure. The final rendering
is stored with the result, keyed by persona, so a GET can return exactly what was checked.

**Rejected:** streaming token-by-token before the judge (violates checked streaming),
trusting the judge's `passed` alone (misses deterministic address-mode and citation errors),
showing the failed narrative with a warning (violates style-never-substance and safety).

## D16 — Rendering and judge output budgets are 8k/6k tokens

**What:** the narrative call gets 8,000 output tokens and the judge 6,000; the OpenAI
adapter forwards `max_tokens`/`max_completion_tokens` only as a lower rendering limit.

**Why:** the provider's reasoning tokens count against the output budget. A 1,600-token
render budget produced an empty content string twice in the live OpenAI test. The
verification call already needed 8,000 for the same reason.

**Rejected:** a premium model for rendering (cost without a quality need), disabling
reasoning (not a documented switch), treating empty content as a successful template
(hides a provider failure).

## D17 — The OpenAI adapter waits on the same durable job

**What:** `/v1/chat/completions` creates the same check job as the native endpoint, polls
its durable state, and only then emits the response or the first SSE chunk. The persona
narrative is fully rendered and checked by the worker before the first content delta.
The adapter accepts exactly one user message in Phase 2; further history returns a clear
`context_not_supported` error.

**Why:** one pipeline, one gate and one result; no second code path with different verdicts.
The checked-streaming invariant requires the substance first and the narrative only after
the check. Accepting history and silently ignoring it would change the meaning of a check.

**Rejected:** a synchronous in-request pipeline (duplicates the worker path and loses
durable partial results), token streaming straight from the provider (unchecked text), a
separate OpenAI pipeline (contract drift).


## D18 — URL checks use a guarded reader and pypdf for PDFs

**What:** a URL submitted for checking is resolved, every resolved address must be public,
redirects are re-validated, the body is capped, HTML is converted to text with the standard
library and PDF text is extracted with `pypdf`. The extracted text becomes the check input;
the URL is provenance in the result and is never ingested.

**Why:** hard invariant 14 (SSRF), the check/corpus separation, and a dependency-free HTML
path. `pypdf` is a small, pure-Python reader that covers the Phase 2 URL case without
pulling Docling's full parsing pipeline into the API process; Docling takes over document
ingestion in Phase 4.

**Rejected:** fetching without resolution checks (SSRF), trusting redirects (redirect
SSRF), a headless browser (execution risk and weight), implementing PDF extraction by hand
(error-prone), adding Docling to the check path before Phase 4 (startup and image cost).


## D19 — Statement events are durable rows, written outside the pipeline transaction

**What:** the pipeline calls an optional `on_statement` callback after each statement; the
worker writes a `job_events` row in a short separate transaction. SSE polls those rows,
replays from `Last-Event-ID`, then emits the result and done events. Cancelling is allowed
only while a job is queued.

**Why:** partial results must survive a reconnect and must not disappear if the final
transaction rolls back. A separate short transaction keeps the pipeline's own transaction
intact and makes the event log the durable source for replay. A running job is not killed
mid-statement; the API refuses to pretend otherwise.

**Rejected:** Redis pub/sub (lost on disconnect), holding the request open with no replay
(no reconnect), writing events inside the pipeline transaction (invisible until commit),
killing a running job without a checkpoint (partial state and half-written files).


## D20 — File checks use the multipart form on the same path, with pinned readers

**What:** `POST /v1/factcheck` accepts `multipart/form-data` with a JSON `payload` part and
one `file` part. PDF uses `pypdf`, DOCX uses `python-docx`, HTML uses the standard-library
extractor, and text/Markdown decode directly. The extracted text is the check input; the
filename, media type and size are provenance. Image files are rejected until the vision
path is wired.

**Why:** the protocol names this endpoint for files, and the check/corpus separation means
the bytes are never ingested. The two pinned readers cover the Phase 2 formats without
pulling Docling into the API process; Docling takes over document ingestion in Phase 4.

**Rejected:** a separate upload path (contract drift), base64 in JSON (memory and size
handling), accepting images without a capable tested vision model (silent failure), adding
Docling to the check request path (startup and image cost).


## D21 — Image input is sanitized with Pillow and read by the vision alias

**What:** image uploads are decoded, EXIF-transposed, stripped of metadata by re-encoding to
PNG, pixel-capped and sent as a data URL to the configured `fs-vision` alias through the
gateway. The vision result is text + description + labels; the normal extraction and gate
then run. The result carries `input.type=image` and the warning
`image_authenticity_not_checked`. Image files are rejected when the model call fails.

**Why:** the vision model is mandatory from the start (PURPOSE §3.10); the image is subject
matter, never evidence; metadata can carry personal data; a silent fallback to text-only
would claim a check that did not happen. Pillow is the smallest pinned library for the
sanitization and dimension cap.

**Rejected:** passing original bytes with EXIF to the provider, checking authenticity
(explicitly out of v1), using the chat model for images (no tested vision capability),
storing the image bytes in the job payload or corpus.


## D22 — Device tokens and feedback are first-class rows, not API-key aliases

**What:** the extension receives a `fc_dev_` token with an explicit permission subset
(default `claims:submit`), stored hashed and revocable; the effective permissions are the
intersection with its owner's. Feedback is one row per user and result, upserted, with
counts and the caller's own value in the claim detail.

**Why:** a device token must not be a long-lived full API key, and revocation must be
immediate. Feedback is content-adjacent and belongs to its author; a unique row prevents
double counting while allowing a user to change their assessment.

**Rejected:** reusing API keys for the extension (too broad), storing device tokens in
plaintext (hard invariant 15), a feedback table per kind (three columns and no single
upsert), anonymous feedback (no author to scope or delete).


## D23 — Conversation context is data; translations are labelled and never evidence

**What:** the last user message is the check input; earlier messages are stored as context
and included in a delimited block for extraction. A deterministic turn heuristic marks a
repeated or follow-up claim; there is no second pipeline. Non-response-language evidence is
translated once in a single structured call; `passage` remains authoritative and the
translation is marked machine-generated. A failed translation leaves the original and adds
`translation_unavailable`.

**Why:** context can resolve scope, but it must not become an instruction or a second claim.
Translations are display/judge context only (PURPOSE §3.9); the evidence hash and citations
still refer to the original. A translation failure must not fail a check that can be decided
from originals.

**Rejected:** asking the model to decide which prior message to check (turn routing as an
LLM verdict source), treating a translation as a citable passage, failing the whole check
when translation is unavailable.

## D24 — The judge sees a longer excerpt and judges support by meaning

**What:** the consistency judge receives up to 1,800 characters per evidence item (not 500)
and is instructed that a faithful paraphrase with a valid citation is supported. The
rendering is still rejected if the judge reports a concrete unsupported citation, an
uncited factual sentence, a verdict contradiction, an unbacked pattern or an unlabeled
translation.

**Why:** the live persona matrix exposed false `unsupported_citations` on a correct
Analyst narrative; the judge was answering from a truncated excerpt. The first live
canonical run after the change passed on attempt 1 with no fallback. The explicit violation
fields remain authoritative; this does not relax the substance rules.

**Rejected:** accepting every citation the model emits (violates invariant 3), removing the
judge, truncating the evidence further to save tokens (caused the false negative).


## D25 — A research summary is withheld unless an independent judge supports it

**What:** the summary model writes cited sentences; code then checks that every sentence
has at least one citation from the response, enforces a short quotation limit on
`metadata_only` sources, and sends the sentences with their cited passages to `fs-verify`
as a consistency judge. The judge checks meaning-level support, verdict/crime/motive
invention, loaded-term adoption and quotation marking. Any failure, judge outage or timeout
returns the lists with `summary=null` and a warning (`summary_consistency_failed` or
`summary_timeout`); there is no retry that strips citations.

**Why:** citation syntax alone does not prove support. Invariant 4 requires attribution and
no assertion, and PROTOCOL §5.2 names the judge explicitly. Failing closed keeps an
unchecked synthesis out of the research surface.

**Rejected:** releasing a syntactically valid summary without the judge, deleting citations
until the judge passes, returning a partial summary, treating a judge outage as a pass.

## D26 — Output moderation distinguishes quoting a claim from asserting it

**What:** the output-moderation call adds a purpose-specific instruction: a fact-check
narrative may quote or describe a discriminatory claim in order to explain why it is
misleading; `discriminatory_generalization` is flagged only when the narrative itself
endorses or asserts the generalization. On any hit the narrative is still replaced by the
deterministic template; the `sexual_minors` hard floor is unchanged.

**Why:** the live German Analyst rendering passed the deterministic checks and the
consistency judge, but output moderation replaced it as `discriminatory_generalization`.
The English rendering passed, so the classifier was reacting to the topic rather than to
an assertion. A fact checker must be able to attribute the claim it refutes. The safety
consequence stays: a flagged narrative is still removed, never released.

**Rejected:** disabling output moderation, exempting a category from replacement, letting
the model keep a narrative that asserts the generalization, changing the hard floor.

## D27 — The LightRAG keyword role is bound to the gateway explicitly

**What:** `deploy/lightrag/lightrag.env` now sets `KEYWORD_LLM_BINDING=openai` with the
gateway host and `fs-extract`, and compose injects `KEYWORD_LLM_BINDING_API_KEY`. The
startup log lists extract, keyword and query roles as `openai/fs-extract`; the VLM role
remains unused.

**Why:** stock LightRAG v1.5.0 has a separate `keyword` role. Without an explicit binding
it inherited the global default, Ollama, and `/query/data` failed with
`Failed to connect to Ollama` even though the extract and query roles were configured.
Invariant 8 requires every model call to go through the gateway.

**Rejected:** setting a global `LLM_BINDING` only (it also affects roles we do not want),
pointing the keyword role at a host Ollama (bypasses the gateway and the data-flow policy),
patching LightRAG.

## D28 — One targeted retrieval round closes an open confounder

**What:** after verification reports `audit_complete = false` and the statement has
checklist confounders, the pipeline builds a second query from the statement plus the
confounder labels and retrieval hints, retrieves once more, and re-verifies only if new
evidence appeared. A retrieval failure leaves the audit open rather than failing the whole
check; the gate still downgrades `true` and records `audit_incomplete`.

**Why:** Phase 3 requires a missing-context claim to trigger a second retrieval and either
fill the gap or return `insufficient_evidence` with an open audit. Re-verifying without new
evidence would add cost without changing the decision; the gate is already the guard that
prevents a clean `true`.

**Rejected:** re-verifying unconditionally after every audit gap, looping until the model
claims completeness (unbounded cost), letting the model itself decide whether to retrieve,
dropping the audit gate for speed.
