# PROTOCOL — Data Contracts & External Interfaces

**Status:** normative. PURPOSE.md explains *why*, IMPLEMENT.md explains *how and when*, this file defines *what goes over the wire*. Where the documents disagree on a data shape or endpoint, this file wins; fix the other documents.

Protocol identifier: **`fcp/1`** (Fact-Check Protocol, version 1). Every installation of this app speaks it both as a **server** (exposing its own corpus and fact-checking) and as a **client** (consuming other installations). Third-party stacks can join a federation by implementing §5 and/or §6.

---

## 1. Conventions

| Topic | Rule |
| --- | --- |
| Base path | `/v1`. Breaking changes require `/v2`; additive changes are allowed within `v1`. |
| Compatibility | Clients **must ignore unknown fields**. Servers send `FCP-Version: 1` on every response. |
| Encoding | JSON, UTF-8, `snake_case`. Timestamps RFC 3339 in UTC. |
| IDs | Prefixed ULIDs: `inst_…` (instance), `doc_…` (document), `psg_…` (passage), `fc_…` (fact-check result), `key_…` (API key). Citation IDs inside one response are short local labels: `E1`, `E2`, … |
| Hashes | `sha256:<hex>` over the normalized UTF-8 text (NFC, `\n` line endings, trimmed). |
| Auth | `Authorization: Bearer fc_live_…`. Keys in query strings are rejected with `400`. |
| Errors | RFC 9457 `application/problem+json` (`type`, `title`, `status`, `detail`). **Exception:** the OpenAI-compatible endpoints (§4.1) use the OpenAI error shape `{"error": {"message", "type", "code"}}`. |
| Rate limits | `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` on every authenticated response; `429` + `Retry-After` on exceed. |
| Pagination | Cursor-based: `?cursor=<opaque>&limit=<n>` → `{"data": [...], "next_cursor": "…" \| null}`. |
| Disabled surface | Every surface has its own feature flag; when disabled, all its paths return `404` (indistinguishable from "does not exist"). |

### 1.1 Surfaces, flags, scopes

| Surface | Paths | Feature flag (default) | Required scope |
| --- | --- | --- | --- |
| Instance info | `GET /v1/instance` | always on (fields can be hidden) | none |
| Fact-check, OpenAI-compatible | `GET /v1/models`, `POST /v1/chat/completions` | `factcheck_api_enabled` (off) | `factcheck:invoke` |
| Fact-check, native | `POST /v1/factcheck`, `GET /v1/factcheck/{id}` | `factcheck_api_enabled` (off) | `factcheck:invoke` |
| Federated evidence | `POST /v1/evidence/query` | `evidence_api_enabled` (off) | `evidence:query` |
| Documents | `/v1/documents…`, `/v1/manifest`, `/v1/changes` | `document_api_enabled` (off) | `documents:read` |
| Snapshot | `GET /v1/snapshot` | `document_api_enabled` (off) | `documents:snapshot` |

Keys may additionally be restricted by: domain tags, expiry date, IP allowlist (optional), per-key quotas (§8).

---

## 2. Enumerations

### 2.1 Verdict

| Value | Meaning | Minimum-source gate applies |
| --- | --- | --- |
| `true` | The claim is accurate and not materially misleading. | yes |
| `true_but_misleading` | The empirical core is accurate, but essential context is missing, so the implied conclusion does not follow. | yes: core ≥ N sources, every `what_is_missing` item ≥ 1 source |
| `partially_false` | Some material parts are accurate, others are false. | yes, per sub-claim |
| `false` | The claim is contradicted by the evidence. | yes |
| `insufficient_evidence` | Checkable in principle, but the available verified evidence does not support a verdict (NEI). Also the target of every gate downgrade. | — |
| `not_checkable` | Normative statements, value judgments, counterfactuals, predictions and unfalsifiable claims. The empirical premises *inside* such statements are still extracted and checked separately. | — |

**Overall verdict (deterministic code, not the LLM)** for inputs that contain several empirical claims:

1. Ignore `not_checkable` parts.
2. All remaining claims `insufficient_evidence` → `insufficient_evidence`.
3. Any `false` and no accurate parts → `false`; any `false`/`partially_false` mixed with accurate parts → `partially_false`.
4. Otherwise any `true_but_misleading` → `true_but_misleading`.
5. Otherwise → `true`.

If some claims are `insufficient_evidence` and others are decided, the overall verdict is computed from the decided claims. The undecided ones are listed in `what_is_unverifiable`.

### 2.2 Evidence tier (retrieval channel)

| Tier | Channel | Verdict-bearing |
| --- | --- | --- |
| 1 | Local corpus (own curated documents *and* documents synced from peers, §6.3) | yes |
| 2 | Live federated evidence from a peer instance (§5) | yes |
| 3 | Validated web search (DOI/URL existence check + content match) | only **in addition to** ≥ 1 tier-1/2 source |
| 4 | LLM parametric knowledge | never; appears only as `unverified_leads` |

### 2.3 Source quality (property of the original publisher, independent of the tier)

| Grade | Typical sources |
| --- | --- |
| `A` | Official statistics, peer-reviewed research, systematic reviews and meta-analyses |
| `B` | Established research institutes, intergovernmental organizations, NGOs with transparent methodology |
| `C` | Quality journalism, grey literature |
| `D` | Advocacy material, unknown or unassessed sources |

The operator configures the minimum grade that counts toward the gate (default `B`). The **effective grade** of evidence that comes from a peer (live or synced) is `min(declared_grade, peer_trust_cap)`. The trust cap is set locally per peer.

### 2.4 Stance

`supports` | `refutes` | `context` (adds missing context, neither confirms nor refutes) | `mixed`.

---

## 3. Core Data Contracts

### 3.1 `Provenance`

```json
{
  "document_id": "doc_01J9...",
  "title": "Police Crime Statistics 2023 — Annual Report",
  "publisher": "Federal Criminal Police Office (BKA)",
  "authors": [],
  "publication_date": "2024-04-09",
  "url": "https://…",
  "doi": null,
  "locator": "p. 12, table 3",
  "dataset_id": "bka-pks-2023",
  "source_quality": "A",
  "source_quality_basis": {"source": "shipped_list", "list_version": "2026.10.1", "entry": "bka.de"},
  "domain_tags": ["politics", "racism"],
  "language": "en",
  "license": "CC-BY-4.0",
  "redistribution": "full_text",
  "curator_organization": "Example Research Network",
  "origin_instance_id": "inst_01J8...",
  "via_instance_id": null,
  "fetched_at": "2025-01-10T09:12:00Z",
  "validation": null
}
```

- `origin_instance_id`: the instance where the document was originally ingested. `via_instance_id`: the peer it was received from (live or synced). Both are `null`/own ID for own documents.
- `redistribution`: `full_text` | `excerpts_only` | `metadata_only` (see §6.1).
- `validation` (tier 3 only): `{"method": "crossref" | "http", "checked_at": "…", "content_match": 0.0–1.0}`.
- `dataset_id` (optional): identifies the underlying primary data, so that two reports built on the same dataset are not counted as independent.
- `source_quality_basis.source`: `document_override` | `local_list` | `shipped_list` | `default_unknown` | `peer_declared` (then capped by the trust cap). It records where the grade came from at retrieval time (PURPOSE §3.1b), so later list changes do not alter stored results.
- `language`: `en` | `de` (PURPOSE §3.11).

### 3.2 `Evidence`

```json
{
  "id": "E2",
  "evidence_id": "psg_01J9...",
  "passage": "After controlling for age, sex and socioeconomic status, …",
  "passage_language": "en",
  "passage_translation": null,
  "passage_hash": "sha256:…",
  "evidence_tier": 1,
  "stance": "context",
  "addresses_confounders": ["age", "sex", "ses"],
  "relevance": 0.87,
  "independence_key": "doi:10.1234/abcd",
  "provenance": { "…": "see 3.1" }
}
```

**Language fields:** `passage` is always the original text and is authoritative. `passage_language` is `en` or `de`. For German passages, `passage_translation` is `{"language": "en", "text": "…", "machine": true, "model_id": "mdl_…", "created_at": "…"}`. A translation is display and judge context only: `passage_hash`, citations and the content match always refer to the original. Peers send originals; the requester translates locally (data-flow policy applies).

**Independence rule (used by the gate):** two evidence items are independent iff their `independence_key` differs **and** they do not share a non-null `dataset_id`. `independence_key` is derived in this order: DOI → canonical URL → `publisher|title|publication_date`. The transport path (local, peer A, peer B) never makes copies independent.

### 3.3 `ClaimAnalysis`

```json
{
  "claim_id": "c1",
  "text": "Immigrants commit more crimes.",
  "kind": "empirical",
  "subject": "immigrant population",
  "predicate": "higher crime rate",
  "time_scope": null,
  "geography": "Germany",
  "population": "residents",
  "quoted_source": null,
  "topics": ["crime_statistics"],
  "domain_tags": ["politics", "racism"],
  "verdict": "true_but_misleading",
  "verdict_rationale": "Raw suspect rates are higher [E1], but … [E2][E3][E4].",
  "what_is_true":         [{"text": "…", "evidence": ["E1"]}],
  "what_is_missing":      [{"text": "…", "confounder": "age", "evidence": ["E4"]}],
  "what_is_unverifiable": [{"text": "…", "reason": "no_disaggregated_data"}],
  "gate": {"required": 2, "independent_sources": 3, "min_quality": "B", "downgraded": false, "reason": null},
  "stale_evidence": false
}
```

`kind`: `empirical` | `implied_conclusion` | `normative`. Implied conclusions are evaluated against the evidence for the empirical claims and against the misleadingness audit. Normative statements get `verdict = not_checkable`.

### 3.4 `FactCheckResult` (the "substance")

The immutable output of the pipeline. Persona rendering never changes it. It is cached under `(normalized_input, corpus_version, pipeline_config_hash)`.

```json
{
  "id": "fc_01J9...",
  "turn_type": "new_claim",
  "status": "complete",
  "input": "Immigrants commit more crimes. That's just what the statistics say.",
  "overall_verdict": "true_but_misleading",
  "claims": [ { "…": "ClaimAnalysis" } ],
  "argument_issues": [
    {"pattern": "omitted_confounders", "explanation": "…", "evidence": ["E2", "E4"]}
  ],
  "evidence": [ { "…": "Evidence" } ],
  "clarification_questions": [],
  "unverified_leads": [],
  "moderation": {"backend": "llm_classifier:mdl_…", "flagged": false, "categories": [], "action": "allow"},
  "warnings": [],
  "pipeline": {
    "version": "0.4.0",
    "corpus_version": "sha256:…",
    "config_hash": "sha256:…",
    "models": {"decompose": "mdl_…", "verify": "mdl_…", "audit": "mdl_…", "translate": "mdl_…"},
    "publisher_list_version": "2026.10.1+local.7"
  },
  "created_at": "2025-01-10T09:12:03Z"
}
```

- `turn_type`: `new_claim` | `repeated_claim` | `follow_up_claim` | `evidence_challenge` | `clarification_answer` | `question` | `meta` | `off_topic` | `abusive` (see PURPOSE §3.2).
- `status`: `complete` | `needs_clarification` | `refused` | `error`.
- For `turn_type = question` (an information request rather than a claim), `overall_verdict` is `null` and the answer points are carried in `claims[].what_is_true` with the same citation rules.
- `argument_issues[].pattern` comes from the versioned pattern taxonomy (PURPOSE §3.1, e.g. `composition_effect`, `base_rate_neglect`, `omitted_confounders`, `cherry_picking`, `scapegoating`, `false_causality`).
- `unverified_leads` (tier 4) is present only if the operator enables it. It is never cited, and it must be shown visually separated from evidence.
- `moderation.action`: `allow` | `flag_only` | `route_abusive` | `block` (PURPOSE §3.8). With `block`, `status = refused` and only a short refusal or support notice is returned. `categories` lists the triggered category ids, never the raw classifier output.
- `warnings`: machine-readable codes, e.g. `peer_unavailable:inst_…`, `stale_evidence`, `consistency_fallback`, `data_flow_restricted`, `web_search_disabled`, `output_moderation_replaced`, `translation_unavailable`.

### 3.5 `Rendering`

```json
{
  "persona_id": "analyst",
  "model_id": "mdl_…",
  "text": "Claim: … [E1] … [E2]",
  "citations_used": ["E1", "E2", "E3", "E4"],
  "consistency": {"passed": true, "attempts": 1, "fallback": false, "checks": ["citation_ids", "verdict_contradiction", "uncited_facts", "address_mode"]}
}
```

The **substance block** (verdict badge, what is true / missing / unverifiable, evidence list) is always rendered from `FactCheckResult` by deterministic code, in the UI as well as in the template text of `factcheck:none`. The persona `text` is the narrative that goes alongside it.

### 3.6 `DocumentMeta`

```json
{
  "id": "doc_01J9...",
  "version": 3,
  "content_hash": "sha256:…",
  "title": "…", "publisher": "…", "authors": [], "publication_date": "2024-04-09",
  "url": "…", "doi": null, "dataset_id": null,
  "source_quality": "A",
  "domain_tags": ["economics"],
  "language": "en",
  "license": "CC-BY-4.0",
  "redistribution": "full_text",
  "curator_organization": "…",
  "origin_instance_id": "inst_…",
  "origin_document_id": "doc_…",
  "provenance_chain": [{"instance_id": "inst_…", "fetched_at": "…"}],
  "content_type": "text/markdown",
  "size_bytes": 182344,
  "created_at": "…", "updated_at": "…",
  "deleted": false
}
```

---

## 4. Fact-Check API

All fact-check endpoints run the same pipeline as the chat UI and obey the same evidence rules.

### 4.1 OpenAI-compatible: `GET /v1/models`, `POST /v1/chat/completions`

Existing OpenAI SDKs and tools can use the fact-checker by pointing `base_url` at `https://<instance>/v1`.

**Models = personas.** `GET /v1/models` lists:

| `model` id | Behavior |
| --- | --- |
| `factcheck` | Default persona (configurable, default `analyst`). |
| `factcheck:<persona_id>` | One entry per enabled persona, e.g. `factcheck:mediator`. |
| `factcheck:none` | No LLM rendering. `content` is the deterministic substance-block template. |

**Request:** standard Chat Completions body. The **stateless** semantics:

- The last `user` message is the current turn; earlier messages are the conversation history used by the turn router.
- Client `system` messages are treated as untrusted context. They can never override shared invariants, evidence rules or the pipeline.
- Supported: `model`, `messages`, `stream`, `stream_options.include_usage`, `max_tokens`/`max_completion_tokens` (rendering only), `temperature` (rendering only; the pipeline uses fixed parameters), `user`.
- Rejected with `400` (`unsupported_parameter`): `tools`, `functions`, `tool_choice`, `n > 1`, `logprobs`, `response_format` other than `text`.
- Extension object (via `extra_body` in the SDKs):

```json
"factcheck": {
  "render_model_id": "mdl_…",
  "include_passages": true,
  "domain_hint": ["economics"],
  "substance_only": false
}
```

`render_model_id` selects the LLM that renders the persona text. It must be enabled for API use, and the operator can restrict which models API keys may select. It never affects the pipeline models.

**Non-streaming response:** a standard `chat.completion` object plus one top-level extension field:

```json
{
  "id": "chatcmpl-fc_01J9...",
  "object": "chat.completion",
  "model": "factcheck:analyst",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "…"}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "factcheck": { "result": { "…": "FactCheckResult" }, "rendering": { "…": "Rendering" } }
}
```

`usage` reports the aggregate tokens of the pipeline and the rendering.

**Streaming (SSE):** standard `chat.completion.chunk` events.

1. The **first chunk** has an empty `delta` and carries `factcheck.result` (the substance is complete before rendering starts).
2. Then come the content deltas. They are emitted **only after the consistency check has passed** ("checked streaming"), so text that is streamed is never retracted.
3. The final chunk carries `finish_reason`, `factcheck.rendering`, and `usage` if requested; then `data: [DONE]`.

**Status mapping:** `needs_clarification` → `content` contains the clarification question(s), `finish_reason = "stop"`. `refused` → `content` contains a short explanation (moderation `block`: `finish_reason = "content_filter"`). If the moderation backend is unavailable, the API fails closed with `503` (`code = "moderation_unavailable"`). Pipeline errors → HTTP 5xx in the OpenAI error shape. Quota or budget exceeded → `429` with `code = "rate_limit_exceeded"` or `"budget_exceeded"`.

### 4.2 Native: `POST /v1/factcheck`

```json
{
  "input": "Average weekly working hours in Germany are particularly low.",
  "context": [{"role": "user", "content": "…"}, {"role": "assistant", "content": "…"}],
  "persona_id": "explainer",
  "render_model_id": null,
  "include_passages": true,
  "domain_hint": []
}
```

- `persona_id: null` → substance only.
- Response `200`: `{"result": FactCheckResult, "rendering": Rendering | null}`.
- With `Prefer: respond-async`: `202` + `Location: /v1/factcheck/{id}`. `GET /v1/factcheck/{id}` returns `{"state": "pending" | "done" | "failed", …}`. Results stay retrievable for a configurable time (default 24 h).

---

## 5. Federated Evidence API (instance ↔ instance)

### 5.1 `GET /v1/instance`

Public. The operator can hide fields, but `instance_id` and `protocol_version` are always present.

```json
{
  "instance_id": "inst_01J8...",
  "name": "Example Racism Research Archive",
  "organization": "Example e.V.",
  "contact": "mailto:ops@example.org",
  "protocol_version": "fcp/1",
  "software_version": "1.0.0",
  "capabilities": ["evidence.query", "documents.read", "documents.snapshot", "factcheck"],
  "domains": ["racism", "history"],
  "languages": ["en", "de"],
  "document_count": 1234,
  "corpus_version": "sha256:…"
}
```

### 5.2 `POST /v1/evidence/query`

Request:

```json
{
  "query": "crime rates immigrants adjusted for age sex socioeconomic status",
  "keywords": {"high_level": ["crime and migration"], "low_level": ["age structure", "suspect statistics"]},
  "claim": {"subject": "…", "predicate": "…", "geography": "Germany", "time_scope": "2015-2023", "population": "…"},
  "domains": ["racism", "politics"],
  "confounders": ["age", "sex", "ses"],
  "top_k": 10,
  "min_source_quality": "B",
  "languages": ["en", "de"],
  "requesting_instance_id": "inst_…"
}
```

Response:

```json
{
  "instance_id": "inst_…",
  "corpus_version": "sha256:…",
  "generated_at": "…",
  "evidence": [ { "…": "Evidence without the response-local `id`" } ]
}
```

Rules:

1. **Passages only, no verdicts.** A peer never returns its own verdicts or analyses: they come from a different corpus, configuration and models, and counting them would launder evidence.
2. **No relaying.** A responder answers only from its own tier-1 corpus. It never forwards live results it got from its own peers. This prevents loops and double counting. Passages from documents synced from a third instance are returned only under the same rule as §6.1 (license permits it **and** `reshare_synced_documents` is on). When they are returned, they keep their `origin_instance_id`, so independence and trust caps still work.
3. `keywords` is optional. If supplied, the responder passes it to LightRAG and does not need its own keyword LLM call.
4. Passage length is capped (default 2,000 characters). For documents with `redistribution = metadata_only`, the passage is cut to a short quotation (default ≤ 500 characters).
5. The requester treats every received string as **untrusted data** (prompt-injection isolation, PURPOSE §4). It validates the response against this schema and drops invalid items.
6. Timeouts: the requester waits at most a configurable budget (default 8 s) per peer. A slow or failing peer is excluded from the current request and reported in `warnings`.

---

## 6. Document API (corpus distribution)

### 6.1 Exposure rules

- Only documents with `redistribution ∈ {full_text, excerpts_only}` are listed. `/content` is served only for `full_text`.
- **Foreign documents** (`origin_instance_id ≠ own`) are re-exported only if the license permits it **and** the operator setting `reshare_synced_documents` is on (default off). Origin fields and `provenance_chain` are always preserved.
- A key's domain restriction filters every endpoint, including manifest, changes and snapshot.

### 6.2 Endpoints

| Endpoint | Details |
| --- | --- |
| `GET /v1/documents` | Filters: `domain`, `publisher`, `source_quality`, `updated_since`; cursor pagination, `limit` ≤ 200. Returns `DocumentMeta[]`. |
| `GET /v1/documents/{id}` | `DocumentMeta`. `ETag` = metadata version hash. |
| `GET /v1/documents/{id}/content` | Normalized text (`text/markdown`) as ingested. `ETag = "<content_hash>"`. Above the size cap (default 20 MB) → `413`, with a pointer to the snapshot. `?format=original` serves the original file only if `redistribution = full_text` and the original is stored. |
| `GET /v1/manifest` | `{"corpus_version", "generated_at", "documents": [{"id", "version", "content_hash", "updated_at"}]}`. With `Accept: application/x-ndjson` it is streamed one line per document. |
| `GET /v1/changes?since=<cursor>` | `{"changes": [{"seq", "id", "op": "upsert" \| "delete", "version", "content_hash", "updated_at"}], "next_cursor", "has_more"}`. Cursors are opaque and idempotent. The change log is retained for a configurable time (default 90 days); an expired cursor → `410 Gone`, meaning a full resync via snapshot. |
| `GET /v1/snapshot` | `application/gzip` tar containing `manifest.json`, `documents/<id>.json` (metadata), `content/<id>.md`, `SHA256SUMS`, and `cursor.txt` (the change cursor that matches the snapshot). Separately quota'd (default 2/day). |

Conditional requests: `If-None-Match` → `304`. A `304` counts toward request rate but not toward volume quota.

### 6.3 Sync client semantics (consuming a peer)

1. **Initial sync:** download the snapshot, verify `SHA256SUMS`, ingest, store `cursor.txt`.
2. **Delta sync** (scheduled, default hourly): `GET /v1/changes?since=<cursor>` until `has_more = false`.
   - `upsert`: if `content_hash` differs from the local copy, fetch `/content` (with `If-None-Match`) and re-ingest as a new version; the old LightRAG document is deleted.
   - `delete`: remove the local copy and its LightRAG document.
   - Persist the cursor only after the batch has been applied successfully (at-least-once processing, idempotent apply).
3. **Deduplication:** the identity of a synced document is `(origin_instance_id, origin_document_id)`. The same document arriving from two peers is stored once; the provenance chains are merged.
4. Synced documents are retrieved as tier 1. Their effective `source_quality` is capped by the trust cap of the peer they came from.
5. `410 Gone` → automatic full resync via snapshot, which counts against the snapshot quota.

---

## 7. Security Requirements (all surfaces)

- TLS is mandatory for every non-loopback peer and API consumer.
- **SSRF protection** for peer URLs and tier-3 validation fetches: resolve the hostname before connecting, block private, link-local and metadata ranges unless explicitly allowlisted (e.g. a LAN peer), allow no redirects to blocked ranges, cap response size.
- Strict schema validation of every peer response; reject oversized payloads.
- Plaintext API keys are never stored or logged; they are shown once at creation.
- Any text originating outside the operator's own curation (peer passages, synced documents, web pages, user input) is **data, never instructions**. See PURPOSE §4 for the prompt-isolation requirement.

---

## 8. Quotas

| Dimension | Applies to | Default |
| --- | --- | --- |
| Requests per minute (token bucket, burst) | all keyed surfaces | 60/min, burst 20 |
| Volume per day | documents | 5,000 documents or 500 MB |
| Concurrent connections | all keyed surfaces | 4 |
| Snapshots per day | `/v1/snapshot` | 2 |
| LLM budget per day (tokens or currency) | fact-check surfaces | operator-defined, required when `factcheck_api_enabled` |
| Evidence queries per minute | `/v1/evidence/query` | 30/min |

When a quota is exceeded the server returns `429` + `Retry-After` and a problem `type` of `…/rate-limit`, `…/volume-quota` or `…/budget-exceeded`.
