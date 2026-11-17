# Phase 6 report — model registry, capability tests, data flow, usage and re-index

Date: 2026-11-17. Stack: Docker Compose, backend/worker from the Phase 6 tree, stock
LightRAG v1.5.0 through the gateway, Postgres with pgvector + AGE, Redis. Live models:
DeepSeek `deepseek-flash` through the gateway, local Ollama `bge-m3` for embeddings and
OpenRouter `google/gemini-2.5-flash` for the vision probe.

## Registry and capability evidence (live)

A DeepSeek provider was added through `POST /v1/config/providers` with the key sent once;
the response contains `has_key=true` and never the key, and the database column holds only
ciphertext (asserted in `test_config.py`). A base model `deepseek-flash` was registered and
probed:

| Probe | Provider | Result | Latency |
| --- | --- | --- | --- |
| chat | DeepSeek | `tested`, `answered` | 1077 ms |
| structured output | DeepSeek | `tested`, `json_schema_honoured` | 1062 ms |
| vision (generated `FS42` image) | OpenRouter | `tested`, `read_test_image` | 1012 ms |
| embedding + cross-lingual | local Ollama `bge-m3` | `tested`, `dimension:1024;cross_lingual_similarity:0.881` | 61 ms |

`PUT /v1/config/roles/fs-extract` with the probed DeepSeek model returned `200` and
`suitable=true`. The same model for `fs-vision` returned `422 assignment_rejected` with
`missing_capability:vision`; `fs-verify` (a wizard binding with no probe) reports
`capability_not_tested:chat` and `capability_not_tested:structured_output`. Every probe
writes a `consumer=probe` usage event (4 calls, USD 0.000137 in this run) and the endpoint
returns `429 budget_exceeded` while the monthly ceiling is reached.

## Data flow (test transport)

The policy editor stores `allow_external` and a `fallback_alias`. With externals disabled
and no fallback, a chat call carrying `user_input` returns `403 data_flow_blocked` and the
test's transport records **zero** provider requests. With `fs-verify` bound to a local model
and configured as fallback, the same call is served with one request to the local base URL.
Embeddings never take a fallback: changing the embedding model needs the re-index lock.

## Budgets

- A key with `requests_per_day=1` gets `429 rate_limit_exceeded` on its second check while
  the owner's session (50/day) still gets `202`.
- The instance ceiling returns the documented `429 budget_exceeded` with `Retry-After`.
- A role budget (`fs-chat=0`) blocks that role only; the free local embedding role still
  serves the semantic cache, so a cache lookup survives an exhausted paid budget.
- Usage totals and the CSV in `test_usage.py` match the recorded events per consumer,
  tokens and cost.

## Publisher overrides (live + tests)

Live: overriding `bka` to grade `D` produced version `2026.02.1+local:256f1ff1`, the diff
showed `shipped A → local D`, and resolve returned grade `D` with
`basis.source=local_list`; restoring removed the local suffix. Tests cover the disputed cap
at `C`, the unknown/duplicate-key rejections, retrieval re-grading (a new check cites the
BKA fixture as `D` with `local_list`) and the cache-impact listing.

## Personas and methodology (live)

Live: three shipped personas listed; a local tone override on `analyst` returned `200` and
the running registry changed; a request carrying `invariants` was rejected `422`; the
Shared Invariants stay identical to the shipped file. A pattern wording override and a
checklist staleness override bumped the local methodology version `v1+local.1.…` and
version `2`. Tests cover the failing canonical example (`422 persona_test_failed`, then
accepted with `override_test=true` and stored `test_issues`), catalog/check validation and
deleting a custom persona while a shipped one is only disableable.

## Re-index (live)

A fixture document was submitted, approved (license confirmed), indexed and counted by
`/v1/instance`. `POST /v1/config/reindex` with `confirm=false` returned `422`; with
`confirm=true` it created a `reindex` job, moved the embedding lock to the current model,
dispatched a `document_index` job and finished `done` with progress 1.0. The document was
re-indexed and the instance document count stayed `1`.

Two real bugs were found by this live run and fixed:

1. `DELETE /documents/delete_document` addresses LightRAG's internal document id, not our
   `doc@v` file source. Passing the source answered `200` while deleting nothing, so the
   re-insert hit `409 Document storage already contains …`. Withdrawal had the same silent
   no-op. The client now lists documents and deletes by the matching internal id
   (`delete_by_file_source`), and the withdrawal test asserts the resolved id.
2. The delete endpoint returns before the asynchronous clearing pipeline finishes; an
   immediate re-insert hit `409 Pipeline is clearing or deleting documents`. The re-index
   now polls until the sources are absent before dispatching the index jobs.

## Spend

- Before this phase's live run (fresh-volume ledger): USD 0.000707.
- This run: USD 0.005824 (document indexing dominated; probes USD 0.000137).
- Cumulative across the project: USD 0.652778 of USD 15.00.

## Tests

`make verify` is green: 76 unit tests, 65 integration tests, migration up/down/up plus
drift, OpenAPI drift and the compose checks. Regular tests use Testcontainers and fakes;
capability probes and provider discovery are faked in tests.

## Follow-up

Per-key monthly USD budget is not a separate gateway check: the gateway attributes spend
to the user and the instance, while a key can tighten the request, text, file and batch
limits. The Phase 6 done-when check (a key at its daily limit) is covered; a per-key USD
ledger is recorded as a later hardening item rather than claimed here.
