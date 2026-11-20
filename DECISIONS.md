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

## D29 — pgvector stores the semantic-cache embeddings; tests use the pinned pgvector image

**What:** `claim_cache.embedding` is a `vector(1024)` column, queried with `<=>` through raw
SQL and cast from a text literal; the `pgvector` Python package supplies the SQLAlchemy
type and the migration. Integration and migration checks now use
`pgvector/pgvector@sha256:484e…` instead of `postgres:16-alpine`, and the app fixture
creates the extension before `create_all`.

**Why:** IMPLEMENT Phase 3 names pgvector in the app DB, and cosine distance belongs in
the database that already holds the corpus. The plain test image has no extension files,
so the schema could not be created there. Raw SQL avoids an asyncpg vector codec for a
column the application only writes and ranks, never reads back.

**Rejected:** storing JSONB embeddings and scanning in Python, a Redis vector store
(second source of truth), registering a custom asyncpg codec just to read the column,
weakening the integration fixture to skip the cache table.

## D30 — Fast mode is an honest preliminary, never a cached verdict presented as final

**What:** a fast request creates the full job and its preliminary result in one
transaction. On a same-corpus/same-response-language cache hit, the preliminary is a copy
of a gated full result marked `preliminary=true` with `preliminary_result` and
`full_result_follows`, and `X-Full-Result-Job` points at the running check. On a miss the
preliminary runs extraction (bounded at 10 s) and returns the statements with a null
verdict; a failed extraction falls back to the raw text as one statement. The worker links
the full result as version 2 with `previous_version_id` set to the preliminary. Fast OpenAI
calls return the preliminary plus `full_result_pending=true`; streaming sends the
preliminary in the first chunk and never a persona narrative.

**Why:** the 15 s target cannot include the remote verification/audit calls. A null-verdict
preliminary cannot contradict the gate, and a cached gated result is labelled as reused
rather than presented as the current check. Creating and storing the preliminary in the
same transaction keeps the job invisible until it can be versioned, so the full result is
always version 2.

**Rejected:** waiting for the full pipeline and calling it fast, fabricating a verdict from
retrieval similarity, releasing a cache hit as final, letting the worker race the
preliminary and produce two version-1 results.

## D31 — The archive lists the newest version and the detail lists the whole chain

**What:** `GET /v1/claims` hides a result that another result supersedes
(`previous_result_id` points at it); `GET /v1/claims/{id}` follows previous-result links
in both directions, returns the newest row as `result`, and lists every version with
`current` set on exactly one row. Feedback remains attached to the version that received
it.

**Why:** a fast preliminary and its full result are two versions of one claim, not two
claims. PROTOCOL §4.4 requires the archive to point at the newest version and to list all
versions. Returning the preliminary as current after the full result exists would show a
stale verdict.

**Rejected:** deleting the preliminary when the full result arrives (it is the durability
record the client already saw), one row overwritten in place (loses the version history),
matching versions by claim text (collides on different claims).

## D32 — Re-checks reuse the stored input; deletion hides the whole chain

**What:** `POST /v1/claims/{id}/recheck` reads the newest version's stored `input.text` and
source metadata, creates a new job with `previous_result_id = current.id`, and records
`recheck=true` plus the reason in the payload. A daily budget
(`recheck_daily_budget`, default 200) counts those jobs and returns `429` over it.
`DELETE /v1/claims/{id}` requires `quality:read`, soft-deletes every version in the chain
and writes an `audit_log` entry; the rows remain for the opaque references held by gaps and
contradictions.

**Why:** PROTOCOL §7.3/§7.4 require re-checks from stored input, not client text, and a
new version link. A client-supplied text would let a caller rewrite an archived claim. Soft
deletion keeps corpus-gap and contradiction references resolvable while the archive hides
the claim.

**Rejected:** re-checking from a request body, hard-deleting rows (breaks gap references),
counting re-checks without a daily cap, a separate deletion permission that the spec does
not define.

## D33 — Document parsing is synchronous; only indexing is asynchronous

**What:** `POST /v1/documents` parses text, URL, PDF, DOCX, HTML and Markdown with the
existing readers and stores the Markdown version plus warnings before returning. It records
a completed `document_parse` job for the audit trail; the 202 response carries that job.
Approval queues `document_index`, which is the only path that writes to LightRAG. Duplicate
content gets state `duplicate` and a `duplicate_of` link unless `force` is set.

**Why:** parsing needs the uploaded bytes or fetched page, and the storage model has no
raw-byte staging yet. Doing it in the request keeps the slice vertical and avoids putting
document bytes in a job payload. Indexing is the slow, externally visible step and stays in
the worker. This is the Phase 4 slice; Docling, figures, scans and batches still follow.

**Rejected:** parsing in the worker without a content store, automatic approval on upload,
serving uploaded HTML, treating a hash duplicate as a new version.

## D34 — Approval and withdrawal trigger bounded re-checks; skipped claims are visible

**What:** after a document is indexed, the worker queues re-checks for current claims whose
statement domain tags overlap the document; withdrawal instead matches results whose stored
evidence references the document. Candidates are de-duplicated by normalized claim text,
capped by the daily re-check budget, and linked to the previous result. If the budget is
exhausted, the document gets a `budget_low` warning with the skipped count; the claim is not
silently dropped. Approval of one's own document is refused with `403 four_eyes_required`
when the four-eyes setting is on.

**Why:** IMPLEMENT Phase 4 requires approval and withdrawal to trigger affected claims
within budget, and the Phase 3 report listed the automatic trigger as open. Bounded,
de-duplicated jobs avoid a corpus update re-checking the same claim many times. A visible
`budget_low` warning is the editor's record that the trigger ran and stopped at the cap.

**Rejected:** re-checking every archived claim on every approval, unbounded queue growth,
dropping over-budget claims without a record, hard-coding four-eyes off.

## D35 — Batches are a bracket of independent document submissions

**What:** `POST /v1/documents/batches` accepts multiple uploaded files, an optional ZIP and
a list of URLs, maps common and per-file metadata, and stores one Document per file with
the shared `batch_id`. ZIP entries with absolute paths, parent traversal or symlink mode
are skipped while safe entries continue; the batch carries `zip_sanitized` warnings.
Counts are `ready`, `warning`, `duplicate`, `failed`; duplicates use the same content-hash
path as single submissions. Batch approval/rejection validates each document and records
per-file results without rolling back successful items.

**Why:** IMPLEMENT Phase 4 requires a batch to survive one bad file and to report per-file
state. Creating ordinary Documents keeps one lifecycle, one warning model and one approval
path; the batch is only a grouping and count record. Skipping unsafe ZIP entries is safer
than rejecting the whole archive and is visible in the response.

**Rejected:** a separate batch-document model (two sources of truth), aborting the batch on
the first failure, trusting ZIP member names, approving a batch as one document.

## D36 — PDF figures go through pypdf and the vision alias; tables wait for Docling

**What:** when a submitted PDF contains embedded images, the route extracts up to five with
pypdf, sanitises each with Pillow, asks `fs-vision` for text and a description, stores a
figure with page, number, description, `description_source = vision` and
`description_model_id`, and appends the description to the Markdown content. A scanned PDF
whose text layer is empty therefore becomes a vision-derived document. Markdown tables are
kept as Markdown; PDF-table reconstruction and OCR layout are not attempted yet.

**Why:** this closes the figure and scanned-page part of Phase 4 without adding Docling's
multi-gigabyte runtime to the build in the same slice. Vision output is data, marked and
editable through the existing figure endpoint. The estimate now includes one vision call
per figure.

**Rejected:** rendering PDF pages (no Poppler in the runtime image), adding an OCR library
whose model lifecycle is another unpinned download, silently accepting an empty PDF,
treating a figure description as evidence without an editor check.

## D37 — Gap re-checks reuse the sampled result inputs and the same daily cap

**What:** `POST /v1/editor/gaps/{id}/recheck` walks the gap's stored sample result ids, reuses
their stored input and source metadata, and creates normal check jobs linked to the
previous result. It shares the daily re-check counter with document-triggered re-checks and
reports `skipped_budget` instead of dropping over-budget claims.

**Why:** PROTOCOL §9.2 requires a gap action that re-checks its samples under budget. Using
the stored input keeps the trigger independent of client text, and one counter prevents two
editor actions from each spending a full daily budget.

**Rejected:** accepting new claim text from the editor, a separate gap budget, silently
skipping the rest.

## D38 — Tables become Markdown through lxml and pdfplumber; Docling stays the layout target

**What:** the shared HTML reader removes each `<table>`, renders its header/body rows as a
GitHub-style Markdown table and appends the blocks to the extracted text. Submitted PDFs
run pdfplumber over up to 20 pages and append up to 10 tables in the same Markdown form.
Both parsers are pinned runtime dependencies; no model download is involved.

**Why:** IMPLEMENT Phase 4 requires tables as Markdown. Docling brings a multi-gigabyte
runtime and a separate model lifecycle; the table requirement is satisfied for digital
HTML/PDF with two small libraries while figures and scans already use the vision path.
Docling remains the plan for layout reconstruction, OCR layout and hard scans.

**Rejected:** flattening tables into running text (loses rows), adding Docling in this slice
without a tested model download, parsing tables with an LLM.

## D39 — Batch metadata sidecars are per-file overrides, not document text

**What:** a `metadata_file` part on `POST /v1/documents/batches` is parsed as JSON (object
keyed by filename) or CSV (`filename,title,publisher,...`); it merges into the existing
per-file overrides, which take precedence over common metadata and are applied to the
document, never to its content. Malformed sidecars are ignored with a warning.

**Why:** PROTOCOL §8.7 allows a CSV/JSON sidecar instead of repeating per-file metadata in
the payload. Keeping overrides out of the parsed text avoids making metadata look like
document evidence. The parser is deliberately small because the v1 columns are fixed.

**Rejected:** putting sidecar values into the Markdown, failing the whole batch on a bad
row, requiring a strict CSV schema.

## D40 — Failed batch entries keep raw bytes only for an explicit retry

**What:** a failed batch parse stores the original bytes and media type on the document
version. `POST /v1/documents/batches/{id}/retry` reparses only those failed entries from
the stored bytes, recomputes metadata warnings and moves the document to `ready` or
`warning`; a second parse failure leaves it failed with the parser message.

**Why:** PROTOCOL §8.7 requires retrying failed files individually. Without the raw bytes
the parser cannot be run again, and re-uploading the whole batch would duplicate the
successful entries. Raw bytes are retained only for failures, not for accepted documents.

**Rejected:** keeping raw bytes for every document (unnecessary storage and retention),
retrying from the parsed Markdown (loses the original), re-running the whole batch.

## D41 — Batch estimates are computed before any model call and checked against the budget

**What:** before a batch creates documents, it counts PDF pages and embedded images,
estimates `pages * 0.0001 + figures * 0.00036` USD, compares it with the remaining monthly
budget, and refuses with `429 budget_exceeded` unless the caller sends
`accept_estimate=true`. Vision calls in a batch carry the batch id as their request id, so
the response can report `actual_usd` from usage events beside the estimate.

**Why:** PROTOCOL §8.7 requires the estimate before processing and a hard budget boundary.
Counting cheaply with pypdf avoids parsing or calling vision first. The request id is the
existing usage correlation, so no new accounting table is needed. The estimate is a
conservative planning number; actual cost is reported separately instead of pretending the
estimate is billing truth.

**Rejected:** starting the batch and stopping midway on budget, estimating from file size
alone, a separate batch-usage table, hiding the estimate/actual difference.

## D42 — Batch PDFs parse figures before deciding the file is empty

**What:** in a batch, a PDF's tables and figures are extracted before the empty-text check;
an image-only or scanned PDF therefore becomes a document with a vision-derived body
instead of `failed empty_input`. The batch vision estimate was tuned to the measured
fixture cost (`0.00023` per figure plus `0.0001` per page).

**Why:** the first live batch with an image-only PDF failed because the text layer was
empty, even though the vision path could read it. Moving the check after asset extraction
keeps the same rule for genuinely empty files. The estimate coefficient now matches the
provider's actual per-figure cost closely enough for the 30% planning target.

**Rejected:** accepting empty PDFs as ready without a body, calling vision before the
budget check, leaving the estimate at a value that overstates cost by more than 70%.

## D43 — Document language is metadata, not a requested response language

**What:** document submission detects the content language and uses the metadata
`language` for the warning and stored provenance; it no longer passes that value as the
response-language override. An unsupported document language becomes
`unsupported_language` on the document instead of a `422`. Past results whose evidence
points at a withdrawn document render that evidence with `provenance.withdrawn = true`
at read time; the stored result row is not mutated.

**Why:** a submitted document may legitimately be in a language the instance does not
answer in; rejecting it made the warning class unreachable and blocked mixed-language
batches. Marking withdrawn evidence in the response keeps stored results immutable while
the UI can show that a cited source is no longer in the corpus.

**Rejected:** rejecting unsupported document languages, mutating historical evidence rows,
hiding withdrawn evidence from past reports.

## D44 — TOTP is enrolled through the web session and recovery codes are one-time

**What:** `/api/auth/totp/setup` stores an encrypted pending secret; `/confirm` verifies a
code, enables TOTP and returns eight recovery codes once while storing only their hashes;
login requires a TOTP or unused recovery code once enabled. Recovery codes are consumed on
use. Privileged accounts without TOTP log in with `totp_setup_required=true` so they can
enrol, rather than being locked out of the setup page.

**Why:** a server-rendered recovery path is safer than requiring a second channel, and the
session already has CSRF protection for the enrolment POST. Storing recovery codes hashed
matches the secret-storage rule. The flag makes the mandatory policy visible; a harder
enforcement pass belongs with the role/setup work rather than blocking the only admin.

**Rejected:** storing recovery codes in plaintext, disabling TOTP with a password alone,
an email reset flow (no email in v1), locking privileged users out before they can enrol.

## D45 — Retention redacts context in place and deletes only unreferenced terminal jobs

**What:** `python -m app.cli retention` redacts `input.context` on results older than
`context_retention_days` (default 90), replacing it with `null` and
`context_redacted = true` while keeping the claim text and result row. It deletes job
events older than 30 days and terminal jobs older than 90 days that no result references.
Every run, including `--dry-run`, writes a `retention_run` audit row with counts. Usage
events are left untouched for the later rollup.

**Why:** old context can contain personal data, but the verdict and citations must remain
for the archive. Deleting a job that a result still references would break provenance, so
the query excludes referenced jobs. The audit row makes the cleanup visible.

**Rejected:** deleting old results, deleting referenced jobs, silently skipping the audit,
redacting claim text itself.

## D46 — Roles are templates; per-user limits sit before the model boundary

**What:** `User.roles` references fixed templates (`admin`, `editor`, `researcher`,
`user`); explicit `permissions` grant more and `denied_permissions` remove; the effective
set is the union of role permissions and grants minus denials, intersected with the known
permission catalog. API keys and device tokens are intersected with that effective set.
`/v1/users` (users:manage) creates/updates users and limits; a manager cannot grant a
permission or role they do not hold. Per-user `requests_per_day`, `text_chars`,
`max_file_bytes` and `max_batch_files` override deployment defaults and are checked before
any model call or job creation.

**Why:** IMPLEMENT Phase 5 requires role templates, multiple roles and limits enforced
before work. Templates keep the policy in code; explicit grants still allow exceptions.
Checking the daily counter before creating a job means a blocked request spends nothing.

**Rejected:** hard-coding permissions per user only, letting a manager escalate beyond
their own set, a separate quota table, enforcing limits after moderation/model calls.

## D47 — The setup wizard is token-gated and completes before any check

**What:** a fresh instance exposes `GET /api/setup/status` and a wizard under `/api/setup`.
Until the first admin exists, `POST /api/setup/admin` and `/admin/totp` require
`SETUP_TOKEN`; after that every wizard step requires a session with `config:manage`.
The admin is created together with a pending TOTP secret and confirms a code before the
wizard proceeds. Provider configuration tests `GET /models` with the stored key and stores
the key encrypted; the moderation step runs one benign sample through the gateway. Only a
complete wizard sets `instance.setup_complete`; checks, research and the OpenAI chat layer
return `503 setup_required` until then. `make bootstrap` remains for CI and reproduces the
same end state.

**Why:** an unauthenticated "create the first admin" endpoint on a reachable host is a
takeover. A deployment token is the smallest control that keeps setup human-only without
adding email. The setup ordering is enforced server-side, not by the future UI.

**Rejected:** trusting the first visitor, relying on a private network, creating an admin
from environment variables again (that path cannot prove provider and moderation work),
finishing setup after a check has already run.

## D48 — Session TOTP is enforced where the privileged permission is used

**What:** `require_permission` rejects a session that lacks an enrolled TOTP when the
route needs `config:manage`, `methodology:manage`, `users:manage`, `documents:review` or
`quality:read`, with `403 totp_setup_required`. The login response advertises the reduced
permission set and `totp_setup_required=true`. API keys and device tokens are machine
credentials and are not asked for a code on every request; their permissions are still
intersected with the owner's effective set.

**Why:** the policy is about the human account, not each transport. Restricting the
session instead of refusing login keeps the enrolment page reachable and makes the block
explicit at the permission boundary. API keys cannot be used to bypass a missing second
factor because creating one through the browser needs the restricted session anyway.

**Rejected:** blocking privileged logins entirely, requiring TOTP per API call (no shared
secret), treating API keys as a second factor.

## D49 — Retention rolls usage events into monthly aggregates before purging details

**What:** `usage_event_retention_days` (default 90) controls the detail window. Retention
groups older events by month, user, consumer, provider and model into `usage_rollups`
(counts, tokens, cost), then deletes the detail rows; the audit row reports both the
rolled-up and the deleted event count. Current-month budget checks keep reading the
unpurged detail rows (the window is longer than a month).

**Why:** cost and quantity history must outlive the request-level events, and hard
invariant 16 says usage shows quantities, not contents. A rollup gives that without
keeping per-request detail beyond the stated period. The unique key makes repeated
retention runs additive instead of duplicating.

**Rejected:** deleting old usage entirely, keeping detail forever, deriving spend only
from the rollup (the current month needs request-level attribution for budgets).

## D50 — Capability probes call the provider directly with synthetic content

**What:** `POST /v1/config/models/{id}/probe` sends a tiny chat, a JSON-Schema request, a
generated test image, an embedding pair and a known moderation hit to the provider's
OpenAI-compatible endpoints. It runs outside the gateway because no alias exists yet for a
model being tested. Prompts contain only fixed synthetic strings; no user input or corpus
content ever leaves the process. Results are stored per model and capability with status
`tested`/`failed`/`assumed`, latency and time.

**Why:** a capability must be proven before a mandatory role may use it, and the gateway
only knows aliases that already exist. Treating this operator action like the setup
provider test keeps the exception narrow and auditable. Rerank has no OpenAI-compatible
probe, so it stays `assumed` and no role requires it yet.

**Rejected:** trusting declared capabilities, probing through a temporary alias (more
moving parts in the gateway), probing with real claims or fixture passages, a probe that
silently downgrades a failure to "assumed".

Probes are charged to the instance: each one records a `consumer = probe` usage event with
the provider's token counts (marked estimated) and the model's price, and the probe is
refused with `429 budget_exceeded` when the monthly ceiling is already reached.

## D51 — Role assignments use one pure rule and need tested capabilities

**What:** `services/capabilities.py` maps each gateway alias to required capabilities,
minimum context, multilingual and embedding dimension. `assignment_reasons` is the single
source used by the assignment endpoint and the role listing (the UI filter will use it
too). A declared but untested capability does not satisfy a role; a binding copies the
model fields and keeps `source_model_id` so probes are not duplicated.

**Why:** hard invariant 10 requires the UI and the backend to agree, and a copied second
rule is how they drift. Copying fields into the alias row keeps the gateway unchanged while
the registry keeps the evidence.

**Rejected:** validating in the route only, accepting declared capabilities, a separate
binding table the gateway would have to join.

## D52 — Publisher overrides re-grade at retrieval and are rebuilt per worker job

**What:** overrides replace a shipped entry's grade/disputed flag by key and never add an
entry. The effective registry is merged at backend startup and again per worker job, so a
re-check grades retrieved documents with the current list instead of trusting the grade
stored at approval. Resolution records `basis.source = local_list` and a version with a
digest of the override set. The impact endpoint lists cached results whose evidence came
from a changed publisher.

**Why:** a grade change must affect new retirements without re-indexing, and a long-running
worker must not keep a stale list. The stored `Document.source_quality` remains the
approval-time value for provenance, while retrieval resolves the effective value.

**Rejected:** editing `publishers.json`, storing grades only at approval, adding unknown
publishers through an override (a silent upgrade path), mutating cached results in place.

## D53 — Persona and methodology overrides live in the database, never in code

**What:** `personas.overrides` and `methodology.overrides` are JSON settings merged over
the shipped files at backend startup and per worker job. Persona overrides can tune the
catalog fields, checks and rules or add a local persona; they cannot touch the Shared
Invariants because the write schema has no such field and the effective registry always
takes the invariants from `PERSONAS.md`. A persona write runs its canonical example
through the deterministic checks and needs `override_test=true` to store a failure.
Methodology overrides may reword an existing pattern or adjust a checklist's staleness and
known confounders; they may not add patterns, topics or confounders, and every write bumps
a local version.

**Why:** the files stay reviewable defaults, while an operator can correct tone or a
stale window without a redeploy. One merge path for backend and worker avoids the stale
config that a per-process cache would create. Rejecting new taxonomy entries keeps a
reviewed change in the repository.

**Rejected:** rewriting `PERSONAS.md`/JSON at runtime, per-process caching, allowing new
patterns through the API, letting a persona write drop the invariants.

## D54 — Re-index addresses LightRAG ids and waits for asynchronous deletion

**What:** the re-index endpoint requires `confirm=true`, moves the embedding lock to the
currently assigned `fs-embedding` model, and creates a `reindex` job. The job resolves our
`doc@v` sources to LightRAG's internal document ids, deletes those ids, polls until the
sources are absent, sets the documents back to `approved` and enqueues one
`document_index` job each. The job is marked done when the dispatch is complete; the
index jobs carry the actual indexing progress. Withdrawal uses the same id resolution.
Document index and re-index jobs now finish as `done` instead of staying `running`.

**Why:** live testing showed that passing a file source to
`DELETE /documents/delete_document` answers `200` but deletes nothing, which made
withdrawal a silent no-op and made re-insert fail with `409 already contains`. The delete
endpoint also returns before the clearing pipeline finishes, so an immediate insert hits
`409 pipeline is clearing`. Resolving ids and polling closes both races. The lock move
happens only here, which is the explicit confirmation the embedding immutability rule
requires.

**Rejected:** patching LightRAG, sleeping a fixed interval, deleting from Postgres and
hoping the index follows, marking the re-index job done before the dispatch (hidden
partial state).

## D55 — Zero-cost calls bypass the paid budget; role budgets are checked in the gateway

**What:** a model whose input and output price are both zero is not blocked by the
monthly budget, so the local `fs-embedding` semantic-cache lookup keeps working when the
paid budget is exhausted. A `budgets.roles` setting adds a monthly USD ceiling per gateway
alias; the gateway sums the role's usage events for the month and returns the documented
`429 budget_exceeded` with `Retry-After`. Per-key daily, text, file and batch limits remain
the key-level ceiling; a per-key monthly USD ledger is a later hardening item.

**Why:** blocking a free local embedding at the paid ceiling would disable the cache and
turn a budget stop into a service stop. A role ceiling lets an operator cap expensive
render/audit calls without touching the user budget. The check sits in the gateway where
every call already passes, not in each pipeline step.

**Rejected:** pre-blocking the fast path, a per-role table instead of a setting, silently
dropping the role check when no limit is configured.

## D56 — The SPA is a static SvelteKit app with generated types and runtime i18n

**What:** `web/` is a SvelteKit SPA (`ssr = false`, adapter-static with an `index.html`
fallback, served later by Caddy). Types come from `docs/openapi.json` through
`openapi-typescript`; `make web-check` regenerates and drift-checks the client. The
dev/E2E server proxies `/v1` and `/api` to the backend. UI copy lives in a TypeScript
catalog for en/de/fr/es and the chosen language is a client preference; verdict labels,
job states and errors are translated, backend prose is not. Mutations send the CSRF token
from `GET /api/auth/session`, which also restores the signed-in user after a reload.

**Why:** the contract is generated, so a backend shape change fails the client build rather
than the browser. A runtime catalog keeps the static build small and lets the language
switch without a reload. The session endpoint exists because an HttpOnly cookie cannot be
read by the SPA to recover the CSRF token.

**Rejected:** server-side rendering (the API is the source of truth and the UI is a
separate static artifact), a hand-written client, per-language builds, storing the CSRF
token in localStorage.

## D57 — The admin console is a guarded UI over the existing config API

**What:** `/admin` pages call the Phase 6 `/v1/config`, `/v1/users` and `/v1/usage`
endpoints directly. The navigation link is shown only for sessions with `config:manage` or
`users:manage`, and the page shows a notice otherwise; the server remains the authority.
Provider keys are write-only in the UI as they are in the API. The Playwright suite uses
route-fulfilled contract fixtures, so it exercises layout, navigation, role assignment and
the re-index confirmation without a TOTP credential or model spend.

**Why:** the console is an operator convenience over tested endpoints; duplicating policy
in the UI would create a second rule. Mocked fixtures are the only way to test the console
without solving the TOTP factor in automation, and the endpoints already have integration
coverage.

**Rejected:** an admin API of its own, exposing provider keys for editing, a live TOTP
secret in test configuration, embedding policy decisions in the pages.

## D58 — The recorded evaluation is a committed prediction file

**What:** `make eval-live` submits the labelled cases through the real API, writes one
prediction per case incrementally to `tests/eval/predictions.baseline.jsonl`, and can resume
an interrupted run. `make eval-recorded` scores that file without a network or a model.

**Why:** a full re-run of 25 cases takes minutes and costs money, so CI and reviewers need a
deterministic replay. Storing predictions instead of full reports keeps generated prose out
of the repository and the baseline reviewable as a diff.

**Rejected:** re-running the live suite in `make verify` (cost, latency, provider flakiness),
committing full reports, scoring a partial run silently (missing predictions and failed
checks are reported as errors or `no verdict`).

## D59 — A document-level source-quality override also applies at retrieval

**What:** when `documents.source_quality_basis.source == "document_override"`, the retrieval
runner uses the stored grade instead of resolving the publisher again.

**Why:** the explicit approval CLI sets a document-level grade for the synthetic corpus;
recomputing it at retrieval silently downgraded all fixture evidence to D and turned every
supported claim into `insufficient_evidence`. The override is the more specific decision.

**Rejected:** special-casing fixture publishers in the publisher list, letting the retrieval
path recompute and ignore an explicit operator decision.

## D60 — Verification caps candidates and output

**What:** at most six candidate passages are sent to the verification model, and the prompt
asks for at most six evidence links, three points per list and a 120-word rationale.

**Why:** with the full fixture corpus, verification produced an 8k-token output that was cut
mid-JSON and retried into the same failure. A bounded prompt keeps the answer inside the
provider's output limit without dropping the audit fields.

**Rejected:** raising `max_tokens` beyond the provider limit, silently accepting a truncated
JSON answer, dropping verification for large evidence sets.

## D61 — Caddy builds and serves the SPA; backups cover the application database

**What:** the edge image builds `web/` and copies the static output into Caddy, which serves
the SPA, `/api`, `/v1` (SSE flushed), health endpoints and blocks `/internal` and `/metrics`.
`make backup` dumps the application database; LightRAG is treated as derived and rebuilt
from approved documents rather than backed up.

**Why:** one origin avoids CORS and keeps the session cookie and CSRF handling simple; the
SSE flush is a proxy setting, not application code. The database holds the authored state
and uploaded originals, while the vector store is reproducible.

**Rejected:** a separate nginx/web container (another origin to configure), backing up the
LightRAG volume (large, derived, inconsistent with the approved corpus after a restore),
enabling the proxy access log (content and query leakage).

## D62 — Source quality is an explicit editorial decision; changes do not re-check

**What:** approval requires an explicit `A`/`B`/`C`/`D` source grade, starting empty in the
editorial UI. An `approved`/`indexing`/`indexed` document can later change its grade through
`PATCH /v1/documents/{id}` or a bulk selection; the change is audited, updates the stored
basis, and does not enqueue re-checks.

**Why:** dpa-factchecking.com has no entry in the shipped publisher list, so all 18 imported
documents graded `D` and could not satisfy the `B` gate even when their text matched. A
silent default would repeat that failure. The human explicitly chose no automatic re-checks:
the stored results keep their original basis and a new check uses the new grade.

**Rejected:** accepting the computed grade by default, approving without a grade, automatic
re-checks of every affected claim after a bulk change (surprise spend and new result
versions), re-indexing for a metadata-only change.

## D63 — Raw retrieval is a separate, filtered LightRAG surface

**What:** `POST /v1/retrieval` and the web page `/retrieval` call stock LightRAG's
`/query/data` (never `/query`) and return matching chunks, entities and relationships
without a verdict, gate, summary or archive hits. Every record is resolved through its
`<document_id>@v<version>` source and returned only for a non-deleted `approved` or
`indexed` document; stale records are counted but not exposed.

**Why:** editors and users need to see what the retrieval layer actually returns when a
check or research query looks empty. This is a diagnostic RAG surface, not a second
fact-check path: LightRAG's answer generation is disabled by invariant 7, and an unfiltered
raw dump would let a withdrawn document reappear during LightRAG's asynchronous deletion.
The human chose raw retrieval and access for all authenticated users.

**Rejected:** calling LightRAG's `/query` answer generation (would change invariant 7),
returning the unfiltered LightRAG payload (withdrawn content), extending `/v1/search` with
a raw flag (would mix the research and diagnostic contracts), recording corpus gaps from
diagnostic queries.

## D64 — The retrieval index is searched with hnsw.ef_search=200, not pgvector's default 40

**What:** the `lightrag` database is initialised with `hnsw.ef_search = 200`; an existing
volume gets the same two statements once by hand (`docs/OPERATING.md`, Retrieval). Nothing
in the application code changes.

**Why:** `/retrieval` returned 12 of 18 documents for `Köln Familien`, and the breakdown
showed two separate causes. This decision fixes the one that can silently lose evidence:
at pgvector's default the HNSW scan reached only 17 of the 28 indexed chunks, independent
of the query (random query vectors with an open threshold: 10–26 of 28). A chunk outside
the beam can never become a candidate, so an approved document was invisible to checks as
well as to the diagnostic page. At 200 the scan returns all 28 with an unchanged top-10
order; 100 was already enough here, 200 keeps headroom while the corpus grows.

**Not changed:** the relevance floor stays at LightRAG's default `COSINE_THRESHOLD=0.2`, so
`/retrieval` still returns almost the whole corpus — all 28 chunks score 0.24–0.55 for
`Köln Familien`, and an unrelated query still matched 16 chunks. Raising the floor changes
check and research evidence and needs a calibration run against the evaluation set.

**Rejected:** dropping the HNSW index (exact, but a sequential scan as the corpus grows);
`hnsw.iterative_scan` (no measured difference once `ef_search` is high, and relaxed ordering
can reorder neighbours); rebuilding the index with a higher `m`/`ef_construction` (an index
rebuild for no measured gain); raising `top_k`/`chunk_top_k` instead (a top-k is a cut, not
a recall setting — at k=40 the same 17 chunks came back).

## D65 — The diagnostic /retrieval surface has its own, smaller graph breadth

**What:** `POST /v1/retrieval` and the page `/retrieval` default to `LIGHTRAG_RAW_TOP_K=10`
and `LIGHTRAG_RAW_CHUNK_TOP_K=20`; checks and research keep `LIGHTRAG_TOP_K=40`. The form
defaults on the page follow the same values.

**Why:** in `mix` mode LightRAG merges graph context and passages into one 30k-token context,
so every entity and relation retrieved is charged against the passages. Measured on the
fixture corpus with `Köln Familien`: at `top_k=40` the response carried 81 entities and 175
relations but only 16 passages from 12 documents; at `top_k=10`, 24 entities and 36 relations
and the full 20 passages from 16 documents; at `top_k=5`, 20 passages from 15 documents. A
wider graph therefore made the diagnostic page show *fewer* documents, which is the opposite
of what a surface for inspecting retrieval should do.

**Not changed:** the check pipeline keeps `top_k=40`. Whether it loses the same passages to
the budget has to be measured on the evaluation set, not assumed from the diagnostic surface.

**Rejected:** lowering the shared `LIGHTRAG_TOP_K` (it moves verdicts and needs the
evaluation set), a second retrieval endpoint (the contract stays one raw surface), keeping
40 and only documenting the effect (the default is what people run).

## D66 — The relevance floor stays at 0.2; the corpus is the problem, not the threshold

**What:** `COSINE_THRESHOLD` stays at LightRAG's stock 0.2. The 0.35 experiment was measured
and reverted; the tree carries no threshold change.

**Why:** 0.35 looked convincing on eight hand-written queries — all eight targets scored
0.547–0.695, the flat tail disappeared, `Köln Familien` dropped from 16 to 6 documents and
`naive` returned nothing for an off-corpus topic. The live evaluation then collapsed from
accuracy 0.640 to 0.280 with 21 of 25 claims becoming `insufficient_evidence`.

**That run does not measure the threshold.** The 25-case set is labelled against
`tests/fixtures/corpus`, and this instance holds the 18 imported dpa documents and no
fixture document at all. The target documents do not exist, so no floor can produce the
labelled verdicts. The 0.640 baseline was recorded on 2026-11-18 08:57; the dpa corpus was
approved that day at 22:28.

**What the run did expose:** 19 of the 28 indexed chunks (68 %) are the publisher footer
(«Über dpa-Faktenchecks … powered by dpa-newslab»). They are near-identical across
documents and sit in the 0.30–0.40 band for almost any query. The one evidence passage the
0.35 run produced for claim-001 was such a footer from an unrelated document. A global
cosine floor therefore keeps the generic tails and drops the specific passages, which score
lower against a paraphrase. Raising the floor cannot fix that.

**Rejected:** 0.35 as a default (keeps boilerplate, drops substance, unvalidated); 0.5
(empties the graph — 0–2 of 543 entities survive); reading the 0.280 run as a regression
(it is a corpus mismatch).

**Follow-up:** remove the publisher footer before indexing and re-index, then re-run the
evaluation on a stack seeded with the fixture corpus. The committed baseline no longer
describes this corpus; `docs/EVALUATION.md` now says so.

## D67 — The publisher footer leaves the index, and it did not change the ranking

**What:** both indexing paths hand LightRAG `strip_publisher_footer(version.content_md)`; the
stored text keeps the footer. Applying it was a re-index of the 18 approved documents.

**Why:** 19 of 28 indexed chunks (68 %) carried the block «Über dpa-Faktenchecks … powered
by dpa-newslab». It is the publisher's programme disclaimer and contact address, identical
across documents, and it does not belong in evidence or in a citation.

**What it did not do:** the similarity landscape barely moved. `Köln Familien` scores 0.540
against the Cologne document (was 0.547) and 0.370 against the best unrelated chunk (was
0.364); an off-corpus query still peaks at 0.333. The flat 0.30–0.40 band is what unrelated
German fact checks score against a short query, not the shared footer — the footer sat in
chunks that are mostly substance. `/retrieval` still returns 15 of 18 documents at the
default floor of 0.2.

**Consequence:** the threshold is the only lever for that band, and it cannot be calibrated
on this instance (D66). The footer rule stays because indexed text should not carry the
publisher's contact block, not because it improves retrieval.

**Operational note:** the first re-index ran against a worker that `docker compose restart`
had not recreated, so it indexed the old text; one document then stalled in `processing`
after a LightRAG deletion error (`'set' object is not subscriptable`) and was repaired by
deleting and re-inserting its source. Two passes were paid for; the second took effect.

## D68 — A relevance cut in our layer decides which LightRAG candidates count

**What:** checks, research and `/retrieval` call one `RelevantRetriever`
(`backend/app/retrieval/relevance.py`). It asks stock LightRAG's `/query/data` for
candidates as before, embeds the scoring text and every candidate passage with the corpus
embedding model through the gateway, and keeps a passage when its cosine similarity is at
least `RETRIEVAL_RELEVANCE_FLOOR` (0.40) and at least the best candidate's score minus
`RETRIEVAL_RELEVANCE_MARGIN` (0.15). The scoring text is the statement for a check (not the
LightRAG query with its appended keywords), the statement plus confounder hints for the
targeted re-retrieval, and the query for research and `/retrieval`. Kept passages are
ordered by score; the score becomes the evidence `relevance` and the passage `score`.
Graph records are kept only if one of their source documents kept a passage. Passage
vectors are cached in `chunk_embeddings` by content hash and locked embedding model. An
embedding failure is `retrieval_unavailable`, never an uncut list (PROTOCOL §5.4).

**Why:** LightRAG's floor (0.2) lies below every passage of a small corpus and its graph
leg brings chunks along whatever their similarity, so `/retrieval` returned 13 of 18
documents for an off-corpus claim and 15 of 18 for `Köln Familien`, and a check's
`no_matching_document` path never fired (docs/RETRIEVAL_FINDINGS.md). Whole-text cosine
separates well where LightRAG does not: on the dpa corpus, 4 off-corpus queries peaked at
0.326–0.338 while 12 on-corpus ones, 8 of them cross-lingual, put their target first at
0.540–0.718. On the fixture corpus the 21 checkable eval claims had a best passage of
0.468–0.885, short cross-lingual topic queries 0.438–0.454, and an off-corpus budget claim
0.404. The floor sits below the weakest genuine match; the margin removes the flat tail
behind a clear match (`Köln Familien`: 0.540 vs at most 0.370) but keeps a contradiction
pair (0.885/0.813) together.

**Measured after the change** (`/retrieval`, defaults): dpa corpus — `Köln Familien` 1
document (Cologne), four off-corpus queries 0 documents, all 12 on-corpus queries keep
their target first with 1–5 documents; fixture corpus — the budget claim 1 document,
German/French/Dutch topic queries 3, 8 and 4 documents, the German burglary claim and its
Dutch translation 1 document each (the German-only target). Latency of a repeated
`/retrieval` query 186–241 ms (214 ms before).

**Evaluation** on a separate Compose project seeded with `make seed-fixtures`, the same
LightRAG index for all runs, full pipeline, three runs each: before 0.560 / 0.640 / 0.720
(mean 0.640), after 0.600 / 0.600 / 0.680 (mean 0.627). No checkable statement in the
after runs lost all its passages (no result carries `no_matching_document`), and cited
evidence per result went from 3.40–3.64 to 3.80–4.24. The
one systematic change is `claim-044` (`contested`): 3/3 before, 1/3 after. In both failed
runs the verifier linked the 5,200 source as `supports` and the 3,900 source as `refutes`
but proposed `insufficient_evidence`, and `gate_statement` returns an
`insufficient_evidence` proposal before it runs contradiction detection. With the
relevance-ordered top six the verifier now sees more context passages and hedges more
often. The gate behaviour is pre-existing and its fix is a gate-rule change, which needs
human confirmation; it was not changed here. The committed baseline file is unchanged.

**Rejected:** raising `COSINE_THRESHOLD` (one floor for chunks, entities and relations,
D66); `naive` mode for checks (drops the graph leg's candidates instead of judging them);
a rerank model (new capability, still a top-k, needs a cut anyway); reading similarity
from LightRAG's tables (not its documented API, invariant 7); failing open when the
embedding is unavailable (silently restores the whole corpus as evidence); scoring
against the LightRAG query with its LLM keywords (the keywords widen the candidate set
but would move the cut with every extraction).
