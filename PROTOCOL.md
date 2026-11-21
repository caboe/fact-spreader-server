# PROTOCOL — Data Contracts & External Interfaces

**Status:** normative. `PURPOSE.md` explains *why*, `IMPLEMENT.md` explains *how and
when*, this file defines *what goes over the wire*. Where they disagree about a data shape,
an endpoint or an error, this file wins; fix the other documents in the same change.

Protocol identifier: **`fcp/1`** (Fact Spreader Protocol, version 1). This revision
defines the **v1 subset**: checks, research, the claim archive, the document pipeline,
usage and the internal LLM gateway. Federation, peer evidence and document sync are v2 and
have no v1 endpoints; the data model is prepared for them (PURPOSE §3.16, §9).

---

## 1. Conventions

| Topic | Rule |
| --- | --- |
| Base path | Public product API: `/v1`. Internal LLM gateway: `/internal/llm/v1` (never exposed by the proxy). Web session/admin API: `/api` (not part of `fcp/1`). |
| Compatibility | Additive changes are allowed inside `fcp/1`. Clients **must ignore unknown fields**. Servers send `FCP-Version: 1` on every `/v1` response. |
| Encoding | JSON, UTF-8, `snake_case`. Timestamps RFC 3339 in UTC with `Z`. |
| IDs | Prefixed ULIDs: `inst_`, `usr_`, `doc_`, `ver_`, `fig_`, `psg_`, `fc_`, `job_`, `bch_`, `key_`, `dev_`, `mdl_`, `prv_`, `per_`, `pub_`, `gap_`, `ctr_`, `evt_`, `sty_`. A job, result, document, version and passage id are opaque strings to clients. |
| Local labels | Inside one result: statements are `S1`, `S2`, …; evidence citations are `E1`, `E2`, … They are stable within that result/version only. |
| Spans | Character offsets are **Unicode code points** into the normalized input text (`input.text`), half-open `[start, end)`. The authoritative text is repeated in `span.text`; clients should locate it rather than trust arithmetic across encodings. For derived text (OCR, a fetched page, a file) `span.source` says where it came from. |
| Hashes | `sha256:<hex>` over normalized UTF-8 text (NFC, `\n` line endings, trimmed) unless stated otherwise. |
| Auth | `Authorization: Bearer fc_live_…` (API key), `Bearer fc_dev_…` (device token), or the web session cookie on `/v1` with CSRF protection on state-changing requests. Credentials in query strings are rejected with `400`. |
| Errors | RFC 9457 `application/problem+json` (`type`, `title`, `status`, `detail`, optional `instance`, `code`, `errors`). **Exception:** the OpenAI-compatible endpoints (§6) use the OpenAI error shape. |
| Rate limits | `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` on authenticated responses. `429` + `Retry-After` on exceed. |
| Pagination | Cursor-based: `?cursor=<opaque>&limit=<n>` → `{"data": [...], "next_cursor": "…" \| null}`. Default limit 20, max 100 unless a section says otherwise. |
| Conditional requests | `ETag` on stable resources; `If-None-Match` → `304` (no body). A `304` counts toward request rate, not volume. |
| Idempotency | `Idempotency-Key` on every state-changing `POST`. The pair (principal, key) is stored 24 h; the same body replays the original response, a different body yields `422 idempotency_key_reused`. Keys are opaque, ≤ 128 characters. |
| OpenAPI | The FastAPI application exports `/openapi.json`. Clients are generated from it. The public `/v1` surface is the Schemathesis target; `/api` and `/internal` are excluded. |
| CORS | Same-origin for `/api`; `/v1` additionally allows the origins of the shipped extension (`chrome-extension://…`, `moz-extension://…`) from an operator-configured allowlist. No wildcard with credentials. |
| TLS | Mandatory for every non-loopback deployment and for every external provider/peer. |

### 1.1 Authentication and permissions

Permissions are the unit; roles are templates (PURPOSE §3.5). An API key or device token
carries a subset of its owner's permissions and never more.

| Permission | Default roles | Used for |
| --- | --- | --- |
| `chat:use` | all signed-in users | chat and check UI |
| `claims:submit` | all users (default on) | `POST /v1/factcheck` |
| `claims:recheck` | editor | re-check a claim, gap-driven re-checks |
| `search:use` | all users | research mode |
| `documents:submit` | reporter, editor | document upload/URL/batch |
| `documents:review` | editor | review queue, approve, reject, withdraw, doc content, corpus gap list |
| `quality:read` | QS, auditor | submitter identities, raw context data, delete archive entries, flagged users |
| `config:manage` | operator | providers, models, data flow, budgets, re-index, settings |
| `methodology:manage` | methodology | checklists, patterns, domains, publishers, personas, language support |
| `users:manage` | operator (separate grant) | users, roles, grants, password resets, TOTP reset |
| `usage:read` | operator | all usage summaries |
| `devices:manage` | own devices; operator all | device tokens and API keys |

- Every signed-in user can read their own usage, devices and API keys.
- API keys are created in the web UI (`/api`), shown once, stored as a SHA-256 hash, have
  an expiry, optional per-key quotas and a permission subset. Prefix `fc_live_`.
- Device tokens are created for the extension, default to `claims:submit`, are shown once,
  stored hashed, and are revocable. Prefix `fc_dev_`.
- The first account has every permission and TOTP is required for it.
- Password login is local only; there is no SSO in v1.

### 1.2 Public, authenticated and internal surfaces

| Surface | Paths | Auth | Permission |
| --- | --- | --- | --- |
| Instance info | `GET /v1/instance` | none | — |
| Models | `GET /v1/models` | bearer/session | `claims:submit` or `search:use` |
| Check | `POST /v1/factcheck`, `GET /v1/factcheck/{job_id}`, `GET /v1/factcheck/{job_id}/events` | bearer/session | `claims:submit` |
| OpenAI-compatible | `GET /v1/models`, `POST /v1/chat/completions` | bearer | `claims:submit` / `search:use` |
| Research | `POST /v1/search` | bearer/session | `search:use` |
| Raw retrieval | `POST /v1/retrieval` | bearer/session | `search:use` |
| Archive | `GET /v1/claims…`, `POST /v1/claims/{id}/feedback` | bearer/session | authenticated |
| Archive re-check/delete | `POST /v1/claims/{id}/recheck`, `DELETE /v1/claims/{id}` | bearer/session | `claims:recheck` / `quality:read` |
| Documents | `/v1/documents…`, `/v1/documents/batches…` | bearer/session | `documents:submit` / `documents:review` by action |
| Review queue | `GET /v1/review/queue` | bearer/session | `documents:review` |
| Indexing status | `GET /v1/review/indexing` | bearer/session | `documents:review` |
| Restart indexing | `POST /v1/documents/{id}/restart-index` | bearer/session | `documents:review` |
| Editor lists | `GET /v1/editor/contradictions`, `GET /v1/editor/gaps` | bearer/session | `documents:review` (methodology also for contradictions) |
| Usage | `/v1/usage…` | bearer/session | own / `usage:read` |
| Devices | `/v1/devices…` | session preferred, bearer allowed | own |
| Internal gateway | `/internal/llm/v1…` | internal key | service consumer |
| Health | `GET /healthz`, `GET /readyz` | none | — |

Disabled or unknown routes return `404`; no route enumerates permissions it would accept.
There are no feature flags in v1. Access is decided by authentication, permission and
deployment configuration.

---

## 2. Enumerations

### 2.1 Verdicts

| Value | Meaning | Gate |
| --- | --- | --- |
| `true` | Accurate as stated and not materially misleading. | yes |
| `true_but_misleading` | Empirical core accurate, essential context missing; the implied conclusion does not follow. | yes: core ≥ N sources, every `what_is_missing` item ≥ 1 source |
| `partially_false` | Some material parts accurate, others false. | yes, per part |
| `false` | Contradicted by the evidence. | yes |
| `contested` | Approved sources support and refute the same statement over the same time scope. | yes: both sides are shown |
| `insufficient_evidence` | Checkable in principle, but the approved corpus does not settle it. Also the target of every gate downgrade and of an unfinished audit. | — |
| `not_checkable` | Normative, predictive, counterfactual, motivational or otherwise unfalsifiable. Empirical premises inside are still checked separately. | — |

`contested` is the seventh value. It is not a synonym for `insufficient_evidence`: it means
the corpus contains both positions, and both are cited.

### 2.2 Overall verdict (deterministic code, never a model)

Given the statement verdicts of one result:

1. Ignore `not_checkable` statements and statements with `checkworthy = false`.
2. If nothing remains: `not_checkable`.
3. If any remaining statement is `contested`: `contested`.
4. If all remaining statements are `insufficient_evidence`: `insufficient_evidence`.
5. If any is `false` and none is accurate (`true`, `true_but_misleading`,
   `partially_false`): `false`.
6. If any is `false` or `partially_false` and at least one is accurate: `partially_false`.
7. Otherwise, if any is `true_but_misleading`: `true_but_misleading`.
8. Otherwise: `true`.

`insufficient_evidence` statements next to decided ones do not block the overall verdict;
they are listed in the report as unverified. A result with `preliminary = true` follows the
same rule; the full run may replace it.

### 2.3 Evidence tier (retrieval channel)

| Tier | Channel | In v1 |
| --- | --- | --- |
| 1 | Local corpus: own approved documents (and, in v2, synced approved documents) | yes, the only verdict-bearing tier |
| 2 | Live federated evidence | no; reserved for a later version |
| 3 | Validated web search | no; out of v1 |
| 4 | LLM parametric knowledge | never verdict-bearing; `unverified_leads` stays empty in v1 |

### 2.4 Source quality (property of the publisher, independent of the tier)

| Grade | Typical sources |
| --- | --- |
| `A` | Official statistics, peer-reviewed research, systematic reviews, meta-analyses |
| `B` | Established research institutes, intergovernmental organisations, NGOs with transparent methodology |
| `C` | Quality journalism, grey literature |
| `D` | Advocacy material, unknown or unassessed sources |

Effective grade resolution, in order: per-document override → local list → shipped list
(`methodology/publishers.json`) → `D`. `disputed: true` caps an entry at `C`. The result
stores the basis that applied at retrieval time, so later list changes never silently
alter a stored verdict. The default gate minimum is `B`.

### 2.5 Gate, contradiction and recency rules (normative)

The gate is pure code. These steps are applied per statement after the structured
verification/audit call, never delegated to a model:

1. **Candidate set.** Tier-1 evidence links for the statement with stance `supports`,
   `refutes` or `context`.
2. **Qualifying set.** Candidates with `provenance.source_quality >= gate.min_quality` and
   pairwise independence (§3.3). The default is `gate.required = 1` because an approved
   document counts as true; deployments may raise it. If there are fewer qualifying
   sources than `gate.required`, every truth-bearing proposed verdict
   (`true`, `true_but_misleading`, `partially_false`, `false`, `contested`) becomes
   `insufficient_evidence`, `gate.downgraded = true`, `gate.reason =
   no_qualifying_source` (or `source_below_min_quality` when candidates existed but none
   qualified).
3. **`true`.** It is only allowed when the audit found no material unaddressed confounder
   and the audit is complete. Otherwise the statement becomes `insufficient_evidence` with
   `gate.reason = audit_incomplete` and warning `audit_incomplete`. A clean `true` is never
   a fast-path default.
4. **`true_but_misleading`.** The core needs a qualifying source. Every item in
   `what_is_missing` must additionally have at least one qualifying, independent evidence
   link and must not cite an evidence ID outside the result. A missing item without such a
   source is moved out of `what_is_missing`; if the claimed misleadingness cannot be
   supported, the statement becomes `insufficient_evidence` with
   `gate.reason = missing_context_unsupported`.
5. **`partially_false`.** The accurate part and the false part are gated separately; if
   either lacks a qualifying source, the statement becomes `insufficient_evidence` with
   the reason for the failing part.
6. **`false`.** Needs a qualifying source with stance `refutes`.
7. **Contradiction.** If the qualifying set contains at least one `supports` and at least
   one `refutes` link:
   - overlapping or unknown time scopes → `contested`, both sides listed in
     `contradictions`;
   - disjoint time scopes → this is a development, not a contradiction. The decisive side
     is the one whose scope matches the statement's `time_scope`; with no statement scope,
     the newest source is decisive and the older side is presented as historical context.
     No `contradictions` record is created.
   `contested` requires qualifying evidence on both sides. If one side is not qualifying,
   it cannot create a contradiction; the qualifying side decides.
   The rule applies whatever verdict the model proposed, including
   `insufficient_evidence`: a proposal that links qualifying `supports` and `refutes`
   sources over overlapping or unknown time scopes becomes `contested`. Only
   `not_checkable` proposals are exempt.
8. **Recency.** For a statement with a present-time or unspecified claim scope, if all
   decisive sources are older than the topic's `staleness_days`, the verdict is capped at
   `insufficient_evidence` with `gate.reason = stale_evidence`; older figures remain in
   `what_is_true` as "true for <year>" context. A past-scoped statement is not capped.
9. **Bypass.** `not_checkable` and `insufficient_evidence` statements do not require a
   qualifying source; an `insufficient_evidence` proposal still passes the contradiction
   rule (7). `insufficient_evidence` is also the target of every downgrade.

Every downgrade records the original proposed verdict in the internal audit log; the
public result shows only the final verdict, the gate block and the warning. The public
`gate.independent_sources` counts the distinct qualifying independence keys actually used.

### 2.6 Stance and statement classification

| Field | Values |
| --- | --- |
| `stance` | `supports`, `refutes`, `context`, `mixed` |
| `kind` | `fact`, `opinion`, `rhetoric`, `implied_conclusion`, `normative` |
| `checkworthy` | boolean; `false` statements carry no verdict |
| `turn_type` | `new_claim`, `repeated_claim`, `follow_up_claim`, `evidence_challenge`, `clarification_answer`, `question`, `meta`, `off_topic`, `abusive` |
| `status` | `complete`, `needs_clarification`, `refused`, `error` |
| `job state` | `queued`, `running`, `done`, `failed`, `cancelled` |
| `output_format` | `substance`, `persona`, `compact` |
| `document state` | `received`, `parsing`, `parsed`, `warning`, `ready`, `approved`, `indexing`, `indexed`, `rejected`, `withdrawn`, `failed`, `duplicate` |
| `batch state` | `uploading`, `estimating`, `processing`, `review`, `approving`, `done`, `partial`, `failed` |
| `moderation.action` | `allow`, `flag_only`, `route_abusive`, `block` |
| `gap state` | `open`, `linked`, `dismissed` |
| `contradiction state` | `open`, `acknowledged`, `resolved` |

---

## 3. Core data contracts

All objects below are JSON. Optional omitted fields are `null` unless stated.

### 3.1 `Instance`

```json
{
  "instance_id": "inst_01J8…",
  "name": "Example Research Archive",
  "organization": "Example e.V.",
  "contact": "mailto:ops@example.org",
  "protocol_version": "fcp/1",
  "software_version": "0.1.0",
  "setup_complete": true,
  "capabilities": ["check", "research", "documents.submit", "claims.archive", "openai.chat"],
  "corpus_version": "sha256:…",
  "document_count": 42,
  "supported_response_languages": ["en", "de", "fr", "es"],
  "supported_corpus_languages": ["en", "de", "fr", "es"],
  "languages": ["en", "de", "fr", "es"],
  "features": {"fast_mode": true, "research_summary": true, "vision": true}
}
```

`instance_id` is created once at first start and never changes. Fields other than
`instance_id`, `protocol_version` and `setup_complete` may be hidden by configuration.
`capabilities` describes what this build implements, not what the caller may use.

### 3.2 `Provenance`

```json
{
  "document_id": "doc_01J9…",
  "document_version": 3,
  "title": "Police Crime Statistics 2023 — Annual Report",
  "publisher": "Federal Criminal Police Office (BKA)",
  "authors": [],
  "publication_date": "2024-04-09",
  "url": "https://…",
  "doi": null,
  "locator": "p. 12, table 3",
  "dataset_id": "bka-pks-2023",
  "source_quality": "A",
  "source_quality_basis": {
    "source": "shipped_list",
    "list_version": "2026.02.1",
    "entry": "bka",
    "declared_grade": null,
    "trust_cap": null
  },
  "domain_tags": ["politics", "racism"],
  "language": "de",
  "license": "CC-BY-4.0",
  "redistribution": "full_text",
  "curator_organization": "Example Research Network",
  "origin_instance_id": "inst_01J8…",
  "origin_document_id": "doc_01J9…",
  "via_instance_id": null,
  "approved_at": "2025-01-09T17:00:00Z",
  "indexed_at": "2025-01-09T17:04:12Z",
  "validation": null,
  "figure": null
}
```

- `source_quality_basis.source`: `document_override`, `local_list`, `shipped_list`,
  `default_unknown`, `peer_declared` (v2).
- `redistribution`: `full_text`, `excerpts_only`, `metadata_only`.
- `approved_at` is public provenance. The approving person is **not** here; it is returned
  only to callers with `quality:read` as `ApprovalRecord`.
- `validation` is reserved for tier-3 web evidence (v2); `null` in v1.
- `figure` is non-null when the passage is a `figure_description`:

```json
{
  "figure_id": "fig_01J9…",
  "page": 12,
  "number": "3",
  "image_url": "/v1/documents/doc_01J9…/figures/fig_01J9…/image",
  "description_model_id": "mdl_…",
  "editor_checked": false
}
```

A `figure_description` is always part of its document, never an independent source. Any
result relying on an unchecked description carries `relies_on_figure_description`.

### 3.3 `Evidence`

```json
{
  "id": "E2",
  "evidence_id": "psg_01J9…",
  "passage": "After controlling for age, sex and socioeconomic status, …",
  "passage_language": "de",
  "passage_translation": {
    "language": "en",
    "text": "…",
    "machine": true,
    "model_id": "mdl_…",
    "created_at": "2025-01-10T09:12:02Z"
  },
  "passage_hash": "sha256:…",
  "evidence_tier": 1,
  "relevance": 0.87,
  "independence_key": "doi:10.1234/abcd",
  "provenance": {"…": "see 3.2"},
  "warnings": []
}
```

- `passage` is always the original and authoritative; `passage_hash`, citations and any
  content match refer to it. A translation is display and judge context only. Evidence in
  an unsupported language carries the warning `unsupported_evidence_language`.
- `evidence_tier` is `1` in v1. `relevance` is 0–1 and is advisory: the passage's cosine
  similarity to the statement from the relevance cut (§5.4). The gate does not read it.
- `independence_key` is derived in order: DOI → canonical URL →
  `publisher|title|publication_date`. Two items are independent iff their
  `independence_key` differs **and** they do not share a non-null `dataset_id`. The
  transport path never makes copies independent.
- Evidence objects are report-global. Per-statement stance lives in the statement's
  `evidence_links`, not here.

### 3.4 `Statement`

```json
{
  "id": "S1",
  "text": "Immigrants commit more crimes.",
  "span": {"start": 0, "end": 33, "text": "Immigrants commit more crimes.", "source": "input"},
  "kind": "fact",
  "checkworthy": true,
  "relevance": 0.95,
  "language": "en",
  "scope": {
    "subject": "immigrant population",
    "predicate": "higher crime rate",
    "geography": "Germany",
    "time_scope": null,
    "population": "residents",
    "quoted_source": null
  },
  "topics": ["crime_statistics"],
  "domain_tags": ["politics", "racism"],
  "verdict": "true_but_misleading",
  "verdict_rationale": "Raw suspect rates are higher [E1], but … [E2][E3].",
  "evidence_links": [
    {"evidence_id": "E1", "stance": "supports", "relevance": 0.9, "addresses_confounders": []},
    {"evidence_id": "E2", "stance": "context", "relevance": 0.88, "addresses_confounders": ["age", "sex", "ses"]}
  ],
  "what_is_true": [{"text": "…", "evidence": ["E1"]}],
  "what_is_missing": [{"text": "…", "confounder": "age", "evidence": ["E2", "E4"]}],
  "what_is_unverifiable": [{"text": "…", "reason": "no_disaggregated_data"}],
  "gate": {
    "required": 1,
    "independent_sources": 3,
    "min_quality": "B",
    "downgraded": false,
    "reason": null
  },
  "relies_on_figure_description": false,
  "warnings": [],
  "clarification_question": null
}
```

- `kind` and `checkworthy` are set by extraction. A non-checkworthy statement has
  `verdict = null`, empty sections, and a `warnings` entry explaining why it was skipped
  (e.g. `not_checkworthy`).
- `scope.time_scope` is either `null` or
  `{"from": "2015-01-01" | null, "to": "2023-12-31" | null, "raw": "since 2015"}`.
  `raw` preserves the claim's wording.
- `what_is_missing[].confounder` is a checklist confounder id when applicable.
- `what_is_unverifiable[].reason`: `no_disaggregated_data`, `stale_evidence`,
  `quote_context_unavailable`, `unsupported_language`, `figure_unchecked`,
  `audit_incomplete`, `translation_unavailable`, `other`.
- `gate.reason`: `null`, `no_qualifying_source`, `source_below_min_quality`,
  `missing_context_unsupported`, `audit_incomplete`, `stale_evidence`,
  `quote_context_unavailable`.
- For `contested`, the statement also appears in the result's `contradictions` list.

### 3.5 `FactCheckResult` (the substance)

```json
{
  "id": "fc_01J9…",
  "job_id": "job_01J9…",
  "version": 1,
  "previous_version_id": null,
  "status": "complete",
  "preliminary": false,
  "turn_type": "new_claim",
  "input": {
    "type": "text",
    "text": "Immigrants commit more crimes. That's just what the statistics say.",
    "language": "en",
    "url": null,
    "file_name": null,
    "media_type": null,
    "size_bytes": null,
    "sha256": "sha256:…",
    "context": {
      "platform": "x",
      "url": "https://…",
      "author": null,
      "published_at": "2026-11-01T10:00:00Z"
    }
  },
  "detected_language": "en",
  "response_language": "en",
  "overall_verdict": "true_but_misleading",
  "overall_explanation": "The core is supported, but the conclusion omits age, sex and reporting effects.",
  "statements": [{"…": "Statement"}],
  "evidence": [{"…": "Evidence"}],
  "contradictions": [
    {
      "id": "ctr_01J9…",
      "statement_id": "S1",
      "supporting_evidence": ["E1"],
      "refuting_evidence": ["E5"],
      "scope_comparison": "same_period",
      "detected_at": "2025-01-10T09:12:03Z"
    }
  ],
  "argument_issues": [
    {
      "pattern": "omitted_confounders",
      "statement_ids": ["S1"],
      "explanation": "The raw association is presented without the variables that explain it.",
      "evidence": ["E2", "E4"]
    }
  ],
  "clarification_questions": [],
  "unverified_leads": [],
  "moderation": {
    "backend": "llm_classifier:mdl_…",
    "flagged": false,
    "categories": [],
    "action": "allow",
    "output_moderation": {"checked": true, "replaced": false, "categories": []}
  },
  "warnings": [
    {"code": "stale_evidence", "statement_id": "S2", "message": "The newest decisive source is from 2019."}
  ],
  "pipeline": {
    "software_version": "0.1.0",
    "pipeline_version": "1",
    "corpus_version": "sha256:…",
    "config_hash": "sha256:…",
    "publisher_list_version": "2026.02.1+local.0",
    "embedding_model_id": "mdl_…",
    "models": {
      "extract": "mdl_…",
      "verify": "mdl_…",
      "audit": "mdl_…",
      "translate": "mdl_…",
      "vision": "mdl_…",
      "judge": "mdl_…"
    },
    "prompt_versions": {"extract": "1", "verify": "1", "audit": "1", "judge": "1"}
  },
  "created_at": "2025-01-10T09:12:03Z",
  "completed_at": "2025-01-10T09:12:31Z"
}
```

- `status`: `complete`, `needs_clarification`, `refused`, `error`. `preliminary` is
  orthogonal. A `preliminary` result is complete enough to show but not the final version.
- `turn_type` is the caller's classification when supplied; otherwise `new_claim`.
  `question` is normally served by research, but a check may return it when the input
  contains no checkable statement.
- `overall_verdict` is `null` only when `status` is `needs_clarification`, `refused` or
  `error`. For a completed result it is always one of the seven verdicts, including
  `not_checkable`.
- `overall_explanation` is deterministic, localized prose from templates. It is not the
  persona narrative.
- `input.text` is the normalized text the spans refer to: the submitted text, extracted
  file text, fetched page text, or OCR/vision text for an image. Raw uploads are not
  retained beyond the archive retention rules. `input.context.author` and `input.url` are
  redacted for callers without `quality:read`; `platform`, date and post id remain.
- `warnings[].code` is one of the machine-readable codes in §3.12.
- A result with `contested`, or with `overall_verdict = insufficient_evidence` and no
  matching document, also creates an editor record (§7).

### 3.6 `CheckResponse`

```json
{
  "result": {"…": "FactCheckResult"},
  "rendering": {"…": "Rendering"} ,
  "compact": {"…": "CompactReport"}
}
```

`rendering` is `null` for `output_format = substance`, for `factcheck:none`, for
`preliminary` results when no narrative was requested, and when rendering failed entirely
(then the deterministic template is still available through the substance). `compact` is
always present for a completed result.

### 3.7 `Rendering`

```json
{
  "persona_id": "analyst",
  "persona_version": 1,
  "model_id": "mdl_…",
  "language": "de",
  "format": "persona",
  "text": "Aussage: … [E1] …",
  "citations_used": ["E1", "E2", "E3"],
  "consistency": {
    "passed": true,
    "attempts": 1,
    "fallback": false,
    "checks": ["citation_ids", "citation_support", "uncited_facts", "verdict_contradiction", "pattern_labels", "translated_quotes", "address_mode"]
  },
  "created_at": "2025-01-10T09:12:34Z"
}
```

On a second failed consistency check the server renders the deterministic template and
sets `consistency.fallback = true` plus the result warning `consistency_fallback`. A
rendered narrative is stored with persona and version for audit; it never mutates the
result.

### 3.8 `CompactReport`

```json
{
  "result_id": "fc_01J9…",
  "version": 1,
  "preliminary": false,
  "verdict": "true_but_misleading",
  "verdict_label": "True, but misleading",
  "bottom_line": "The core is supported; the conclusion omits the context that changes it.",
  "missing_contexts": ["Age structure", "Suspects vs. convictions"],
  "key_evidence": [
    {"citation": "E1", "publisher": "BKA", "publication_date": "2024-04-09", "url": "https://…"}
  ],
  "report_url": "/reports/fc_01J9…",
  "language": "en",
  "warnings": []
}
```

Everything in `CompactReport` is deterministic, localized template output. The extension
shows the badge (`verdict`), `bottom_line`, two or three `missing_contexts` and
`report_url`; it does not receive a persona prompt or a rendered narrative unless it asks
for one.

### 3.9 `Job`

```json
{
  "id": "job_01J9…",
  "kind": "check",
  "state": "running",
  "progress": 0.5,
  "result_id": null,
  "batch_id": null,
  "document_id": null,
  "created_at": "2025-01-10T09:12:00Z",
  "started_at": "2025-01-10T09:12:01Z",
  "finished_at": null,
  "poll_after_ms": 800,
  "events_url": "/v1/factcheck/job_01J9…/events",
  "error": null
}
```

`kind`: `check`, `recheck`, `document_parse`, `document_index`, `batch`, `research_summary`,
`reindex`. `error` is a small object `{code, message, retryable}` for failed jobs. Partial
results are durable; a reconnect can always rebuild the view from the result.

### 3.10 `Document`

```json
{
  "id": "doc_01J9…",
  "version": 3,
  "content_hash": "sha256:…",
  "title": "…",
  "publisher": "…",
  "authors": [],
  "publication_date": "2024-04-09",
  "url": "…",
  "doi": null,
  "dataset_id": null,
  "source_quality": "A",
  "source_quality_basis": {"source": "shipped_list", "list_version": "2026.02.1", "entry": "bka"},
  "domain_tags": ["economics"],
  "language": "de",
  "license": "CC-BY-4.0",
  "redistribution": "full_text",
  "curator_organization": "…",
  "origin_instance_id": "inst_…",
  "origin_document_id": "doc_…",
  "provenance_chain": [{"instance_id": "inst_…", "approved_at": "…"}],
  "content_type": "text/markdown",
  "size_bytes": 182344,
  "state": "ready",
  "warnings": [{"code": "duplicate_suspected", "message": "A near-duplicate of doc_… exists."}],
  "duplicate_of": null,
  "submitted_by": null,
  "approval": null,
  "figures": [],
  "created_at": "…",
  "updated_at": "…",
  "deleted": false
}
```

- `submitted_by`, `approval.approved_by`, raw context data and `quality:read` fields are
  present only for the submitter or a caller with `documents:review` or `quality:read`.
- `approval` is `{"approved_at": …, "approved_by": "usr_…", "note": null}` when approved.
- `figures` entries follow §3.11.
- `state` follows §2.6. `approved`, `indexing` and `indexed` are distinct: editorial
  approval does not mean the document is already retrievable.
- A document that exists only as a submission is visible to its submitter and to
  `documents:review`; it is not in the corpus and cannot be cited.

### 3.11 `Figure`

```json
{
  "id": "fig_01J9…",
  "page": 12,
  "number": "3",
  "caption": "Figure 3: Registered suspects by age group",
  "description": "Bar chart …",
  "description_source": "vision",
  "description_model_id": "mdl_…",
  "editor_checked": false,
  "editor_checked_by": null,
  "created_at": "…",
  "image_url": "/v1/documents/doc_01J9…/figures/fig_01J9…/image"
}
```

`editor_checked = true` only after an editor corrected or confirmed the description; then
the passage is editorially checked and loses the `figure_unchecked` marker.

### 3.12 Warnings

Warnings are `{"code": string, "statement_id"?: string, "message": string}`. Codes in v1:

`stale_evidence`, `audit_incomplete`, `gate_downgraded`, `no_matching_document`,
`quote_context_unavailable`, `quote_translated`, `translation_unavailable`,
`unsupported_language`, `unsupported_evidence_language`, `figure_unchecked`,
`relies_on_figure_description`, `image_authenticity_not_checked`, `consistency_fallback`, `output_moderation_replaced`,
`moderation_flagged`, `injection_suspected`, `provider_fallback`,
`data_flow_restricted`, `budget_low`, `preliminary_result`, `full_result_follows`,
`duplicate_suspected`, `license_missing`, `low_source_grade`, `parse_warning`,
`zip_sanitized`, `summary_consistency_failed`, `partial_batch`, `peer_unavailable` (v2).

Unknown warning codes must be ignored by clients.

### 3.13 `ResearchResponse`

```json
{
  "query": "Donald Trump ministers corruption",
  "detected_language": "en",
  "response_language": "en",
  "documents": [
    {
      "document": {
        "id": "doc_…",
        "title": "…",
        "publisher": "…",
        "publication_date": "…",
        "source_quality": "A",
        "language": "de",
        "url": "…",
        "license": "…",
        "redistribution": "full_text"
      },
      "passages": [
        {
          "evidence_id": "psg_…",
          "passage": "…",
          "passage_translation": null,
          "locator": "p. 3",
          "score": 0.82,
          "figure": null
        }
      ]
    }
  ],
  "claims": [
    {
      "result_id": "fc_…",
      "claim_text": "…",
      "verdict": "true_but_misleading",
      "created_at": "…",
      "excerpt": "…"
    }
  ],
  "summary": {
    "text": "According to … [E1] …",
    "language": "en",
    "citations": [{"sentence": 0, "evidence_ids": ["psg_…"]}],
    "consistency": {"passed": true, "attempts": 1, "fallback": false},
    "model_id": "mdl_…",
    "created_at": "…"
  },
  "warnings": [],
  "took_ms": 1830
}
```

`summary` is `null` unless requested. Each sentence of the summary carries at least one
citation; the citations refer to `psg_` ids in `documents`. A failed consistency check
returns `summary = null` and the warning `summary_consistency_failed`. Research has **no
verdict** and never adopts value-laden query terms as fact.

### 3.14 Archive and editor records

`ArchiveEntry`:

```json
{
  "result_id": "fc_…",
  "version": 1,
  "claim_text": "Immigrants commit more crimes.",
  "language": "en",
  "overall_verdict": "true_but_misleading",
  "topics": ["crime_statistics"],
  "domain_tags": ["politics", "racism"],
  "created_at": "…",
  "preliminary": false,
  "has_contradiction": false,
  "submitted_by": null
}
```

`submitted_by` is present only for the submitter, or for a caller with `quality:read`; the
UI displays "you" or a role, not names, to ordinary users.

`CorpusGap`:

```json
{
  "id": "gap_…",
  "state": "open",
  "query": "2026 revision changed the rules",
  "normalized_topic": "revision of the rules",
  "language": "en",
  "topics": ["…"],
  "frequency": 7,
  "sample_result_ids": ["fc_…"],
  "first_seen": "…",
  "last_seen": "…"
}
```

`Contradiction`:

```json
{
  "id": "ctr_…",
  "state": "open",
  "statement_text": "…",
  "result_ids": ["fc_…"],
  "supporting": [{"evidence_id": "psg_…", "document_id": "doc_…", "locator": "…"}],
  "refuting": [{"evidence_id": "psg_…", "document_id": "doc_…", "locator": "…"}],
  "detected_at": "…",
  "acknowledged_by": null,
  "acknowledged_at": null
}
```

Both lists are visible to `documents:review`; contradictions additionally to
`methodology:manage`.

---

## 4. Check API

### 4.1 `POST /v1/factcheck`

**Request (JSON).**

```json
{
  "input": {
    "type": "text",
    "text": "Average weekly working hours in Germany are particularly low.",
    "language": null
  },
  "context": [
    {"role": "user", "content": "…"},
    {"role": "assistant", "content": "…"}
  ],
  "turn_type": null,
  "mode": "async",
  "fast": false,
  "persona_id": null,
  "render_model_id": null,
  "output_format": "substance",
  "response_language": null,
  "include_passages": true,
  "domain_hint": []
}
```

**Input object.**

| `input.type` | Fields | Notes |
| --- | --- | --- |
| `text` | `text`, `language?` | Trimmed; max 20,000 chars (role limit). Empty → `422 empty_input`. |
| `url` | `url`, `language?` | SSRF-guarded fetch; default 10 s, 20 MB; extracted main text becomes `input.text`. |
| `file` | upload part + optional `language` | Multipart only; PDF, DOCX, HTML, Markdown, plain text, images; max 20 MB/file (role limit). |
| `image` | upload part, or JSON `image_url` + `media_type` | Vision path; not an authenticity check. Max 15 MB, 20 megapixels. |

- Multipart form: a `payload` part containing the JSON above plus one or more `file` parts.
  `input.type` is inferred from the uploaded media unless given. A `text` input may not
  carry a file.
- `context` is untrusted data, never instructions. It is used for scope and follow-ups; it
  is included in the stored result only as redacted metadata and text excerpts according
  to retention.
- `turn_type` accepts the values in §2.6. If omitted, the server classifies new/repeated/
  follow-up using the archive; `question` is normally routed to research by the UI.
- `mode`: `async` (default) or `sync`. `sync` is the fast path: it requires
  `fast = true`, text ≤ 5,000 chars or one image, and returns a `preliminary` result; the
  full check is enqueued automatically. A non-fast sync request is `422 sync_requires_fast`.
- `fast`: run the fast path. With `mode = async`, the job returns a preliminary result and
  then a full result version.
- `persona_id`: `null` for substance only. Must be an enabled persona.
- `render_model_id`: rendering model override; must be enabled for API use and allowed for
  this key. It never affects pipeline models.
- `output_format`: `substance` (default), `persona`, `compact`. `persona` requires a
  `persona_id`; `compact` is deterministic and needs no persona.
- `response_language`: one of the supported codes, or `null` for the input language;
  unsupported requested language → `422 unsupported_response_language`. The verification
  rationale and substance points are written in this language; evidence passages stay in
  their original language.
- `include_passages`: when `false`, evidence passages are shortened to 300 chars and
  translations are omitted from the response (the gate still uses full passages).
- `domain_hint`: advisory domain tags; never a wall.

**Response (sync, `200`).** `CheckResponse` plus headers:

- `ETag: "<result_id>:<version>"`;
- `X-Result-Preliminary: true|false`;
- `X-Full-Result-Job: job_…` when a full follow-up was enqueued;
- `Idempotency-Key` echo.

**Response (async, `202`).**

```json
{
  "job": {"…": "Job"},
  "poll_after_ms": 500
}
```

`Prefer: respond-async` is accepted as an alias for `mode = async`. `Prefer:
respond-sync` with `fast = true` is accepted. `Location` points at
`/v1/factcheck/{job_id}`.

**Limits and validation.** `413 payload_too_large`, `415 unsupported_media_type`,
`422 invalid_input`, `422 sync_requires_fast`, `422 unsupported_response_language`,
`403 permission_denied`, `429 budget_exceeded` / `rate_limit_exceeded`, `503
moderation_unavailable`, `502 provider_unavailable`, `504 job_timeout`. A rejected input
still records a moderation/usage event with the data content omitted.

### 4.2 `GET /v1/factcheck/{job_id}`

```json
{
  "job": {"…": "Job"},
  "result": {"…": "CheckResponse"} 
}
```

`result` is `null` while the job is queued/running, unless partial statements are
available, in which case `result` contains a `preliminary` result with the finished
statements and `status = complete`. A finished full result has `preliminary = false`. The
endpoint supports `ETag` and `If-None-Match`. Polling interval is at least
`poll_after_ms`; clients must honour `Retry-After` after `429`.

### 4.3 `GET /v1/factcheck/{job_id}/events` (SSE)

`Content-Type: text/event-stream`. Events:

| Event | Data | Meaning |
| --- | --- | --- |
| `state` | `Job` | state/progress changed |
| `statement` | `Statement` | one more statement is ready (partial result) |
| `result` | `CheckResponse` | preliminary result ready |
| `warning` | `Warning` | non-fatal warning |
| `done` | `{"job": Job, "result_id": "fc_…"}` | terminal; the client fetches the result |
| `error` | `{"code", "message", "retryable"}` | terminal failure |

Each event has an `id:` that is monotonically increasing within the stream. A client may
reconnect with `Last-Event-ID`; if the server cannot replay from that point it sends the
current `state` and, when available, a `result` event. A `: keepalive` comment is sent
every 15 s so proxies do not close idle connections. The server enforces a maximum stream
duration (default 30 min) and then closes; clients reconnect.

### 4.4 Partial results, versions and cancellation

- Individual statements become durable as they finish. A `preliminary` result may contain
  only those statements and `overall_verdict = null` if no statement is final yet; once at
  least one statement is final, the overall verdict is computed over the final ones.
- The final result is a new version. `GET /v1/claims/{result_id}` lists all versions and
  points at the newest.
- `DELETE /v1/factcheck/{job_id}` cancels a queued or running job if it has not started
  irreversible work; the result becomes `status = error`, `error.code = cancelled`. A
  finished result cannot be cancelled, only deleted by QS.

---

### 4.5 Moderation gate

Moderation is mandatory for every check input and every chat turn. There is no unchecked
path; if the configured backend is unavailable, the request fails closed with `503` and
problem type `moderation_unavailable`.

- **Input policy for checks:** flag and continue. A discriminatory generalisation
  submitted for checking is the product's core case. Only `sexual_minors` is blocked and
  it is not configurable. For the **check pipeline**, every other category action is
  interpreted as `flag_only`, regardless of the stricter chat policy; this is a hard rule,
  not an operator setting.
- **Sexual-minors hard floor:** before the configured classifier runs, a narrow
  deterministic guard detects explicit sexual content involving a minor and blocks it. It
  is not configurable and does not depend on the backend being available. Its record uses
  the backend id `hard_floor:sexual_minors`. It is deliberately narrow so that legitimate
  discussion of child abuse remains checkable; the configured classifier still covers the
  rest of the category.
- **Chat policy:** the stricter configured policy applies to the user's own statements.
  `route_abusive` triggers one neutral de-escalation; repeated abuse ends substantive
  engagement for the session. A blocked chat input returns a short refusal, not the
  classifier output.
- **Output policy:** only the persona narrative is moderated, not the deterministic
  substance. On a hit the narrative is replaced by the deterministic template, the result
  warning `output_moderation_replaced` is recorded, and the rendering is stored with the
  moderation outcome. The substance is never rewritten.
- **Images:** image inputs are moderated with a vision-capable moderation model before the
  vision description and pipeline run.
- **Stored record:** `FactCheckResult.moderation` contains the backend id, `flagged`,
  triggered category **ids** (never raw classifier text), the action and whether output
  moderation replaced text. The same record is written to the audit log.
- **Flagged users:** repeated flags appear in the QS view. A flag alone never blocks the
  user's ordinary checks; only the category policy and the explicit block above do.
- **Configuration:** backend, fallback, category actions, output moderation, help
  resources and a test console are operator settings in `/api`. A moderation test must pass
  before first-run setup completes or the first check is accepted.

## 5. Research API

### 5.1 `POST /v1/search`

```json
{
  "query": "Donald Trump Minister korrupt inkompetent",
  "response_language": null,
  "filters": {
    "from": "2015-01-01",
    "to": "2026-11-16",
    "domains": ["politics"],
    "languages": ["en", "de"],
    "min_source_quality": "B"
  },
  "summary": false,
  "limit": 20,
  "cursor": null
}
```

- `query` max 2,000 chars.
- `filters` are optional and apply to documents and passages, not to archive hits.
- `summary = true` requests the cited summary. It is LLM work and is budgeted.
- `limit` max 50.
- Response `200`: `ResearchResponse` (§3.13). `202` is not used; if the summary takes
  longer than the configured request timeout (default 60 s), the list is returned with
  `summary = null` and `warnings = [{"code": "summary_timeout"}]`, never a partial summary.
- A query with no document hits writes a `CorpusGap` (`frequency` incremented) and
  `gaps_recorded = true`.
- Research has no verdict and no persona narrative. `role` is `researcher`.
- Documents and passages pass the same relevance cut as check evidence (§5.4); a passage
  `score` is its cosine similarity to the query.
- `POST /v1/search` with an invalid/oversized query is `422`; budget is `429`; an
  unavailable LightRAG or relevance embedding is `503` with `retrieval_unavailable`.

### 5.2 Summary consistency

The summary is generated from the retrieved passages only and checked before release:

1. every sentence has ≥ 1 citation that exists in the response;
2. a judge confirms each cited passage supports its sentence;
3. no sentence asserts a verdict, a crime or a motive not stated by a source;
4. loaded terms from the query are not adopted; direct quotes are marked and attributed;
5. licence rules for `metadata_only` documents cap quotation length.

On failure the endpoint returns `summary = null`, the lists, and the warning
`summary_consistency_failed`. There is no retry that removes citations; a second failure is
final for the request.

### 5.3 `POST /v1/retrieval` — raw retrieval

This is **not a fact check**. It calls stock LightRAG's retrieval endpoint (`/query/data`)
and returns the matching passages and graph records after the same relevance cut a check
applies (§5.4), so it shows what a check would see. It never calls LightRAG's answer
generation (`/query`), and it returns no verdict, gate, summary or archive hits. It does
not write a corpus gap or any other editorial record.

```json
{
  "query": "housing costs",
  "mode": "mix",
  "top_k": 40,
  "chunk_top_k": 20,
  "include_graph": true
}
```

- `query` max 2,000 chars. `mode` is one of `mix`, `local`, `global`, `hybrid`, `naive`
  (default `mix`). `top_k` and `chunk_top_k` are 1–100 and default to the deployment
  retrieval values. `include_graph` defaults to `true`.
- Response `200` is a `RawRetrievalResponse`:

```json
{
  "query": "housing costs",
  "mode": "mix",
  "top_k": 40,
  "chunk_top_k": 20,
  "documents": [
    {
      "document": {
        "id": "doc_...",
        "version": 1,
        "title": "Housing report",
        "publisher": "Example Institute",
        "publication_date": "2026-01-02",
        "source_quality": "B",
        "language": "en",
        "url": "https://example.org/report",
        "license": "CC BY 4.0",
        "redistribution": "full_text"
      },
      "chunks": [
        {
          "chunk_id": "doc-...-chunk-001",
          "reference_id": "1",
          "content": "Rent prices rose faster than incomes.",
          "file_path": "doc_...@v1",
          "score": 0.612,
          "order": 0
        }
      ]
    }
  ],
  "entities": [],
  "relationships": [],
  "relevance": {
    "floor": 0.4,
    "margin": 0.15,
    "top_score": 0.612,
    "cut_chunks": 14,
    "cut_entities": 9,
    "cut_relationships": 21
  },
  "returned_chunks": 1,
  "dropped_chunks": 0,
  "returned_entities": 0,
  "dropped_entities": 0,
  "returned_relationships": 0,
  "dropped_relationships": 0,
  "took_ms": 42
}
```

- Every chunk, entity and relationship carries a LightRAG `file_path` of the form
  `<document_id>@v<version>`. It is returned only if that version exists and the document
  is not deleted and is `approved` or `indexed`. Other records are counted in `dropped_*`
  and never returned. This closes the window in which LightRAG still serves a withdrawn
  document before its asynchronous deletion finishes.
- Documents are ordered by their best passage score. `relevance` reports the cut: its
  `floor` and `margin`, the best `top_score` among the candidates (`null` without
  candidates), and how many passages, entities and relationships it removed. An entity or
  relationship is kept only if one of its source documents kept a passage. Stale records
  are removed first and counted in `dropped_*`, not in `relevance`.
- `include_graph = false` returns empty `entities` and `relationships` arrays and zero
  graph counts; passage retrieval still runs.
- Permission is `search:use`. An invalid mode or query is `422`; an unavailable LightRAG
  or relevance embedding is `503` with `retrieval_unavailable`. The endpoint has no
  generated answer, so it adds no summarization cost; LightRAG's own keyword and embedding
  calls and the relevance embeddings go through the gateway and its budget rules.

### 5.4 Relevance cut

Stock LightRAG ranks by count, not relevance: on a small corpus its candidate set is
most of the corpus for almost any query. Checks, research and raw retrieval therefore
apply one cut to LightRAG's candidate passages, in code:

1. each candidate passage is embedded with the corpus embedding model (`fs-embedding`,
   through the gateway; cached per passage hash and model) and scored by its cosine
   similarity to the scoring text: the statement for a check, the statement plus the
   confounder hints for a targeted re-retrieval, the query for research and raw retrieval;
2. a passage is kept if its score is at least `RETRIEVAL_RELEVANCE_FLOOR` (default 0.40)
   **and** at least the best candidate's score minus `RETRIEVAL_RELEVANCE_MARGIN` (default
   0.15).

A check statement without a kept passage takes the `no_matching_document` path
(`insufficient_evidence`, corpus gap). The score becomes the evidence `relevance` and the
passage `score`. A failure of the relevance embedding fails the retrieval; it never
returns the uncut list.

---

## 6. OpenAI-compatible surface

### 6.1 `GET /v1/models`

Rows follow the OpenAI list shape and add an extension object:

```json
{
  "object": "list",
  "data": [
    {
      "id": "factcheck",
      "object": "model",
      "created": 1763334000,
      "owned_by": "fact-spreader",
      "factcheck": {
        "kind": "check",
        "persona_id": "analyst",
        "output_formats": ["substance", "persona"],
        "fast": true,
        "streaming": true
      }
    },
    {
      "id": "factcheck:straight-talker",
      "object": "model",
      "created": 1763334000,
      "owned_by": "fact-spreader",
      "factcheck": {
        "kind": "check",
        "persona_id": "straight-talker",
        "output_formats": ["substance", "persona"],
        "fast": true,
        "streaming": true
      }
    },
    {
      "id": "factcheck:none",
      "object": "model",
      "created": 1763334000,
      "owned_by": "fact-spreader",
      "factcheck": {"kind": "substance", "persona_id": null, "streaming": true}
    },
    {
      "id": "factcheck:research",
      "object": "model",
      "created": 1763334000,
      "owned_by": "fact-spreader",
      "factcheck": {"kind": "research", "persona_id": null, "streaming": true}
    }
  ]
}
```

`factcheck` is the default persona (configured; `analyst` unless changed). One row per
enabled persona. Only personas the caller may use are listed. `factcheck:none` returns
deterministic substance text and makes no rendering call. `factcheck:research` maps to
`POST /v1/search`.

### 6.2 `POST /v1/chat/completions`

Standard Chat Completions body. Semantics:

- The last `user` message is the current input; earlier messages are context. System
  messages are untrusted context, never instructions.
- Supported: `model`, `messages`, `stream`, `stream_options.include_usage`, `max_tokens` /
  `max_completion_tokens` (rendering only), `temperature` (rendering only), `user`.
- Rejected with `400` / `code = "unsupported_parameter"`: `tools`, `functions`,
  `tool_choice`, `n > 1`, `logprobs`, `response_format` other than text, audio, and unknown
  top-level fields that would change semantics.
- Extension object via `extra_body`:

```json
"factcheck": {
  "persona_id": null,
  "render_model_id": null,
  "output_format": "substance",
  "response_language": null,
  "include_passages": true,
  "domain_hint": [],
  "fast": false,
  "summary": false
}
```

- `persona_id` conflicts with a `factcheck:<persona>` model → `400 persona_conflict`.
- `fast = true` returns a preliminary deterministic result immediately after the fast
  pipeline, plus `factcheck.job_id` and `factcheck.full_result_pending = true`; the
  narrative is not attempted for a preliminary result. The client polls the native job for
  the full result. This is the path for the extension.
- Non-fast requests run the full pipeline before any content is sent.

**Non-streaming response:**

```json
{
  "id": "chatcmpl-fc_01J9…",
  "object": "chat.completion",
  "created": 1763334000,
  "model": "factcheck:analyst",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "…"},
      "finish_reason": "stop"
    }
  ],
  "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
  "factcheck": {
    "result": {"…": "FactCheckResult"},
    "rendering": {"…": "Rendering"} ,
    "compact": {"…": "CompactReport"},
    "job_id": null,
    "full_result_pending": false
  }
}
```

`usage` is the aggregate of pipeline and rendering tokens. For `factcheck:none` the
`content` is the deterministic substance template and `rendering` is `null`. For
`factcheck:research` the extension object is:

```json
"factcheck": {
  "kind": "research",
  "summary": true,
  "filters": {"from": null, "to": null, "domains": [], "languages": [], "min_source_quality": null}
}
```

and the response carries `factcheck.research` (a `ResearchResponse`) instead of
`factcheck.result`.

**Streaming.** Standard `chat.completion.chunk` events plus:

1. The first chunk has an empty `delta` and carries `factcheck` (the full substance for a
   full run, or the preliminary compact result for fast mode).
2. Content deltas follow only after the consistency check has passed ("checked streaming").
   Text that has been streamed is never retracted. For fast mode no narrative is streamed;
   the deterministic compact text is sent in one delta.
3. The final chunk carries `finish_reason` and `factcheck.rendering` / `usage` when
   requested, then `data: [DONE]`.
4. `: keepalive` comments may be sent while the pipeline runs.

**Status mapping.**

| Condition | HTTP | Content / code |
| --- | --- | --- |
| `needs_clarification` | 200 | clarification question(s), `finish_reason = "stop"` |
| moderation `block` | 200 | short refusal, `finish_reason = "content_filter"` |
| moderation unavailable | 503 | `moderation_unavailable` |
| budget exhausted | 429 | `budget_exceeded` |
| rate limit | 429 | `rate_limit_exceeded` |
| bad parameter | 400 | `unsupported_parameter` |
| pipeline/provider error | 502/504 | OpenAI error shape, retryable flag in `code` |

Errors on this surface use `{"error": {"message", "type", "code", "param"}}`, never RFC
9457.

---

## 7. Claim archive API

### 7.1 `GET /v1/claims`

Query: `query`, `verdict` (repeatable), `topic`, `domain`, `language`, `from`, `to`,
`mine=true`, `preliminary`, `cursor`, `limit`.

Response: paginated `ArchiveEntry`. Search is full-text over claim text and topics, plus
semantic ordering when `query` is present. All authenticated users see all entries; the
submitter identity is redacted per §3.14.

### 7.2 `GET /v1/claims/{result_id}`

Returns:

```json
{
  "result": {"…": "CheckResponse"},
  "versions": [
    {"result_id": "fc_…", "version": 2, "created_at": "…", "preliminary": false, "current": true}
  ],
  "feedback": {"helpful": 4, "unhelpful": 1, "incorrect": 0, "my_feedback": null},
  "submitted_by": null
}
```

An archived result is never mutated. A re-check or a finished full check creates a new
`fc_` result and a version link. `DELETE /v1/claims/{result_id}` (`quality:read`) soft-deletes
all versions and writes an audit event; the corpus gap/contradiction records keep an
opaque reference.

### 7.3 `POST /v1/claims/{result_id}/feedback`

```json
{"kind": "helpful|unhelpful|incorrect", "comment": "optional, ≤ 500 chars"}
```

One feedback per user per result; a second call replaces the previous one. Response `204`.
Feedback comments are content and visible only to `quality:read`.

### 7.4 `POST /v1/claims/{result_id}/recheck`

`claims:recheck`. Body `{"reason": "corpus_changed|manual", "fast": false}`. Creates a new
check job from the stored input (not from a client-supplied text), with the current corpus
and configuration. Response `202 {job}`. The daily re-check budget applies; over budget →
`429 budget_exceeded`.

---

## 8. Document API

All document content is untrusted data. Uploaded files are never served as HTML; parsed
text is served as `text/markdown` with a sandboxing `Content-Security-Policy`.

### 8.1 `POST /v1/documents`

JSON (URL or pasted text):

```json
{
  "input": {"type": "url", "url": "https://…"},
  "metadata": {
    "title": null,
    "publisher": null,
    "authors": [],
    "publication_date": null,
    "url": null,
    "doi": null,
    "dataset_id": null,
    "license": null,
    "redistribution": null,
    "domain_tags": [],
    "language": null,
    "source_quality_override": null
  },
  "batch_id": null
}
```

Multipart: `payload` (JSON) plus `file`; `input.type` is `file` or `image`.

Response `202`:

```json
{
  "document": {"…": "Document"},
  "job": {"…": "Job"},
  "estimate": {"pages": 12, "figures": 3, "vision_calls": 3, "estimated_usd": 0.04, "exceeds_budget": false},
  "duplicate_of": null
}
```

A duplicate may return `200` with `document.state = duplicate` and `duplicate_of = doc_…`
instead of creating a new version. The editor can still submit it explicitly with
`"force": true` when the duplicate is intentional (the reason is recorded).

### 8.2 `GET /v1/documents/{document_id}`

Returns the `Document` (§3.10). The submitter sees their own; `documents:review` sees all;
others get `404` for unapproved documents. Approved documents are discoverable through
research but not individually public by id without that permission.

### 8.3 `GET /v1/documents/{document_id}/content`

`text/markdown`, `ETag = "<content_hash>"`. Visible to the submitter before approval and to
`documents:review`; after approval, also to any caller with `documents:review` (v1 has no
public document API). `?version=<n>` serves an older version to reviewers. A content size
over the configured cap returns `413` with a note; v1 does not expose snapshots.

### 8.4 `PATCH /v1/documents/{document_id}`

Change the source quality of an `approved`, `indexing` or `indexed` document:

```json
{"source_quality": "A|B|C|D", "note": "why the grade changed"}
```

`documents:review` is required. The change is audited with the previous grade and does not
re-index the document or enqueue re-checks; a later approval of a new version or a corpus
re-index is the normal way to revisit verdicts. Content changes still require withdrawal
and a new version; v1 has no in-place content edit and no public versions endpoint.

### 8.5 Approval and lifecycle

| Endpoint | Permission | Body | Effect |
| --- | --- | --- | --- |
| `POST /v1/documents/{id}/approve` | `documents:review` | `{"license_confirmed": true, "redistribution": "full_text|excerpts_only|metadata_only", "source_quality": "A|B|C|D", "note": null}` | state `approved`; sets the source grade; enqueues indexing; records approver |
| `POST /v1/documents/{id}/reject` | `documents:review` | `{"reason": "…"}` | state `rejected`; never indexed |
| `POST /v1/documents/{id}/withdraw` | `documents:review` | `{"reason": "…"}` | removes from LightRAG, marks withdrawn, triggers re-checks for affected claims |
| `PUT /v1/documents/{id}/figures/{figure_id}` | `documents:review` | `{"description": "…"}` | editor correction; `editor_checked = true` |

- `license_confirmed` must be `true`; missing license is a warning, not a hard block, but
  the editor must explicitly confirm the metadata is correct.
- `source_quality` is required and must be `A`, `B`, `C` or `D`; a missing grade is
  `422 validation_error`. The UI starts the choice empty so a grade cannot be accepted by
  accident. Every approval records the previous grade and the basis `document_override`.
- Approval of a document submitted by the same person is allowed unless the four-eyes
  setting is on; then it is `403 four_eyes_required`.
- Approving an already approved document returns `409 invalid_state`.
- The approver must have `documents:review`; an API key can carry it only if its owner does.
- Indexing is asynchronous. Until `indexed`, the document is not citation-capable. The
  corpus version changes when indexing completes.
- `POST /v1/documents/{id}/reindex` is not public; re-indexing is an operator action in
  `/api`.

### 8.6 Review queue

`GET /v1/review/queue` (`documents:review`) returns `data: [Document]`, `counts` and a
summary. Filters: `state` (default: pending, which includes `ready`, `warning`, `parsed`
and `duplicate`; `all` for every state), `q` (title, publisher or URL), `source_quality`
(`A`–`D`), `publisher`, `language`, `published_from`, `published_to`, `limit` (max 200).
`state=ready` returns both `ready` and `parsed`, matching the Ready counter. `counts`
includes `indexing` and `failed`; indexing progress is `indexed / (approved + indexing +
indexed)`. Documents without warnings are flagged `approval_preselected = true`; documents
with warnings are not.

#### Indexing status and restart

A document counts as indexed only after its own LightRAG `track_id` reports `processed`.
An empty track immediately after the insert is not success: LightRAG enqueues the text in a
background task after returning the track id. A `failed` track fails the job. The worker
does not wait for LightRAG's global document queue, so an unrelated pending document cannot
block it.

`GET /v1/review/indexing` (`documents:review`) returns the documents currently in the
`indexing` state, split into `active` and `aborted`. Each item carries the latest
`document_index` job's id, state, attempts, error, start time and a `stale` flag. A job is
aborted when it is failed, absent, or still `running` for more than 20 minutes (the worker's
wait for one document's LightRAG track is bounded at 15 minutes). A queued or fresh running
job is active.

`POST /v1/documents/{id}/restart-index` (`documents:review`) accepts only an `indexing`
document whose latest job is aborted. An active job is `409 index_job_active`; a
non-indexing document is `409 invalid_state`. A successful restart sets the document to
`approved` and queues a new `document_index` job with `clean_before_insert: true`. The
worker deletes the old `<doc>@v<version>` source and waits until LightRAG has finished
removing it before inserting again, so a partial previous insert cannot duplicate the
document.

### 8.7 Batch upload

`POST /v1/documents/batches` (multipart):

| Part | Content |
| --- | --- |
| `payload` | JSON: common metadata, `license`, `redistribution`, `domain_tags`, `publisher`, per-file `overrides` keyed by filename, `urls`, `force` |
| `files` | zero or more uploaded files |
| `archive` | optional ZIP; expanded with ZIP-bomb, path-traversal and symlink protection |
| `metadata_file` | optional CSV/JSON sidecar with per-file metadata |

Response `202`:

```json
{
  "batch": {
    "id": "bch_…",
    "state": "estimating",
    "counts": {"total": 0, "ready": 0, "warning": 0, "duplicate": 0, "failed": 0},
    "estimated_usd": 0.0,
    "budget_remaining_usd": 12.4,
    "files": [],
    "created_at": "…",
    "updated_at": "…"
  }
}
```

- Limits: default 100 files, 200 MB total, 20 MB per file, 10,000 URLs. Role bounds override
  downward, never upward beyond the deployment cap. Exceed → `413`.
- Every file is a document; one failure does not fail the batch. Duplicates are detected
  within the batch and against the corpus. A ZIP that needed sanitising gets the warning
  `zip_sanitized`.
- Cost estimate rules: pages, figures and vision calls are estimated before processing; the
  batch does not start if the estimate exceeds the remaining budget, unless the caller has
  the budget and confirms with `"accept_estimate": true` (still bounded by the actual
  budget).
- `GET /v1/documents/batches/{batch_id}` returns counts, files, estimate and state.
  Pagination for `files` when > 100 (`?cursor`).
- `POST /v1/documents/batches/{batch_id}/retry` `{"document_ids": […]}` retries failed
  files only.
- `POST /v1/documents/batches/{batch_id}/approve` `{"document_ids": […], "license_confirmed": true, "redistribution": "…", "source_quality": "A|B|C|D", "note": null}`.
  The server validates each document state and four-eyes rule; per-file errors are returned
  in `results` and do not roll back successful approvals. Documents with warnings may be
  approved explicitly; the UI does not preselect them. `source_quality` is required.
- `POST /v1/documents/batches/{batch_id}/reject` `{"document_ids": […], "reason": "…"}`.
- Batch processing continues in the worker when the browser closes. A batch is a bracket
  around independent documents, never one document.

### 8.8 Bulk source quality

`POST /v1/documents/quality` (`documents:review`):

```json
{"document_ids": ["doc_…", "doc_…"], "source_quality": "B", "note": "same publisher assessment"}
```

Up to 200 documents. Only `approved`, `indexing` and `indexed` documents are changed;
invalid ids or states appear as per-document `error` entries and do not roll back the
others. Every change is audited separately and no re-checks are enqueued. The endpoint is
intended for the editorial list's select-all/quality header.

### 8.9 Duplicates and versions


- Duplicate key: `content_hash` first; then `(origin_instance_id, origin_document_id)`;
  then a normalized title/date/publisher heuristic marked as *suspected*.
- A suspected duplicate is a warning; a hash duplicate is a hard `duplicate` state for new
  submissions of the same content.
- Document identity is stable across versions. A new version of an already approved
  document requires withdrawing the old version first or using the operator re-index flow;
  the v1 UI does not offer in-place content edits.
- A withdrawn document is removed from LightRAG and can no longer be cited in new results;
  stored past results keep their evidence and provenance, marked `withdrawn` in the UI.

---

## 9. Editor lists

### 9.1 `GET /v1/editor/contradictions`

Permission: `documents:review` or `methodology:manage`. Filters: `state`, `from`, `to`,
`cursor`, `limit`. Response: paginated `Contradiction` plus counts. `PATCH
/v1/editor/contradictions/{id}` with `{"state": "acknowledged|resolved"}` records who and
when. Resolving a contradiction does not change any verdict; it only closes the editorial
record.

### 9.2 `GET /v1/editor/gaps`

Permission: `documents:review`. Filters: `state`, `sort=frequency|last_seen`, `cursor`,
`limit`. Response: paginated `CorpusGap` plus counts. `PATCH
/v1/editor/gaps/{id}` with `{"state": "linked|dismissed"}`. `POST
/v1/editor/gaps/{id}/recheck` re-checks up to `limit` sample results (budget-checked) and
returns `202 {jobs: [Job]}`.

---

## 10. Usage API

### 10.1 `GET /v1/usage/me`

Returns the caller's own consumption and limits for `from`/`to` (default current month):

```json
{
  "period": {"from": "2026-11-01", "to": "2026-11-30"},
  "currency": "USD",
  "requests": {"total": 120, "by_channel": {"web": 80, "plugin": 30, "api": 10, "openai": 0}},
  "checks": {"total": 90, "fast": 60, "full": 30, "rejected": 2},
  "submissions": {"documents": 4, "batches": 1},
  "llm": {"tokens_in": 120000, "tokens_out": 40000, "cost_usd": 0.84},
  "limits": {"requests_per_day": 500, "llm_budget_usd_month": 10.0, "text_chars": 20000},
  "budget": {"remaining_usd": 9.16, "resets_at": "2026-12-01T00:00:00Z"},
  "rejected": {"rate_limit": 1, "budget": 1, "moderation": 0}
}
```

Only quantities, no claim text, titles or document names.

### 10.2 `GET /v1/usage/summary`

`usage:read`. Query: `from`, `to`, `group_by` (`user|provider|model|role|channel|verdict|day`,
repeatable), `format=json|csv`. Returns aggregate cards, time series and breakdowns for
tokens, costs, requests, checks, rejections, latency (median/p95), cache hit rate, queue,
provider error rate, circuit breaker state, verdict distribution, contradictions,
consistency fallbacks, moderation hits and feedback. Costs are USD. When
`Accept: text/csv` or `format=csv`, the response is `text/csv` with a header row; the
exported data contains no contents.

### 10.3 `GET /v1/usage/budget`

Returns the instance monthly ceiling, current spend, remaining amount, reset time and
whether cache-only mode is active. Available to every signed-in user in a reduced form;
`usage:read` sees instance-wide figures.

---

## 11. Device tokens

### 11.1 `POST /v1/devices`

Session-authenticated (or a bearer credential with `devices:manage`). Body:

```json
{"name": "Firefox on macOS", "permissions": ["claims:submit"]}
```

`permissions` is optional and defaults to `claims:submit`; it may never exceed the owner's
permissions. Response `201`:

```json
{
  "device": {
    "id": "dev_…",
    "name": "Firefox on macOS",
    "permissions": ["claims:submit"],
    "created_at": "…",
    "last_seen_at": null,
    "revoked_at": null
  },
  "token": "fc_dev_…"
}
```

The plaintext `token` is returned **once**. Only its hash is stored.

### 11.2 `GET /v1/devices`, `DELETE /v1/devices/{device_id}`

Own devices; `devices:manage` sees all. `DELETE` revokes immediately. The web "Connect
plugin" screen calls this endpoint after login and hands the token to the extension through
a one-time `state`; the extension stores it in its own secure storage. The exact handoff is
a frontend concern; the server never sends the token anywhere else.

### 11.3 API keys

API keys are created in the web UI (`/api/api-keys`), not through the public `/v1` surface.
The contract is the same: a permission subset, an expiry, optional quotas, prefix
`fc_live_`, hashed at rest, shown once. Keys never exceed their owner.

---

## 12. Internal LLM gateway

The gateway is the only path to a model. It is not part of `fcp/1` and must never be
proxied by Caddy. It is OpenAI-compatible so that LightRAG can use it with documented
configuration and stock code.

### 12.1 Endpoints

| Endpoint | Purpose |
| --- | --- |
| `POST /internal/llm/v1/chat/completions` | chat and vision (OpenAI message content, including `image_url`) |
| `POST /internal/llm/v1/embeddings` | embeddings |
| `GET /internal/llm/v1/models` | gateway aliases available to the caller |

### 12.2 Authentication and headers

- `Authorization: Bearer fc_int_…` — one key per internal consumer, from deployment
  configuration (not the public API key table). Rotating it is a restart.
- `X-FS-Consumer`: `lightrag`, `pipeline`, `render`, `moderation`, `research`. Recorded in
  usage; LightRAG's calls are attributed to `lightrag`, not to a single document.
- `X-FS-Data-Classes`: comma-separated classes carried by the call: `own_corpus`,
  `user_input`, `figure_description`, `moderation`, `search_query`.
- `X-FS-Request-Id`: opaque correlation id; echoed.
- `X-FS-Purpose`: `ingestion`, `query`, `semantic_cache`, `render`, `moderation`,
  `research_summary`. Used for the embedding lock and usage breakdown.
- Missing or invalid internal key → `401`; a public key on this path → `403`.

### 12.3 Model aliases and routing

- The operator assigns gateway aliases to roles: `fs-chat` (rendering), `fs-extract`
  (LightRAG extraction and pipeline extraction), `fs-verify`, `fs-audit`, `fs-judge`,
  `fs-embedding`, `fs-vision`, `fs-moderation`, `fs-rerank`.
- LightRAG is configured statically with `fs-extract` and `fs-embedding` and never needs a
  restart when the mapping changes. A model registry change updates the gateway mapping.
- `model` in the OpenAI body is the alias. `role:<name>` is accepted as a convenience for
  the backend; unknown aliases → `404 model_not_found`.
- Vision requests require a model with tested `vision`; embeddings require a tested
  `embedding` model with the expected dimension; structured-output roles require tested
  `structured_output`; otherwise `422 model_capability_missing` with the reason.
- The data-flow policy is applied before the provider call: if a rule forbids sending the
  call's data classes to an external model, the gateway tries an allowed fallback; if none
  exists, it returns `403 data_flow_blocked`. It never silently sends to a forbidden
  provider.

### 12.4 Embedding and figure-model lock

The corpus has one embedding model and dimension. The gateway records the lock when the
first document is indexed. An embedding call whose resolved model or dimension differs is
rejected with `409 embedding_model_locked` unless the operator has started an explicit
re-index, which sets a short-lived override. The same lock applies to the vision model used
for corpus figure descriptions. Chat rendering models are not locked.

### 12.5 Budgets, usage and errors

- Every call checks the consumer's budget (user/key/instance) before dispatch and records
  a usage event with provider, model, role, consumer, tokens, cost, latency, status and
  data classes. Contents are never recorded.
- Exhausted budget → `429` with problem type `budget_exceeded` and `Retry-After`; cache hits
  remain available to the check pipeline.
- Provider timeout/5xx → retry within the configured budget, then `502 provider_unavailable`
  or `504 provider_timeout`. The circuit breaker per provider/model opens after repeated
  failures and returns `503 circuit_open` until the cooldown.
- Streaming is passed through; usage is recorded when the stream completes or is aborted.
- Errors use the OpenAI error shape.

---

## 13. Limits, quotas and budgets

Defaults; role/user bounds can lower them, never raise them above the deployment cap.

| Dimension | Applies to | Default |
| --- | --- | --- |
| Requests per minute (token bucket) | `/v1` keyed surfaces | 60/min, burst 20 |
| Concurrent jobs | per user | 4 |
| Text length | check | 20,000 chars (sync 5,000) |
| File size | check/document | 20 MB |
| Image | check | 15 MB, 20 MP |
| Files per batch | document batch | 100 |
| Batch size | document batch | 200 MB |
| URLs per batch | document batch | 10,000 |
| Documents per day | document ingestion | 5,000 or 500 MB |
| Snapshots per day | v2 only | — |
| LLM budget per day/month | per user, key, instance | operator-defined, required |
| Re-check budget per day | corpus-change re-checks | operator-defined |
| Requests to `/internal` | per consumer | deployment-defined |

Headers on every authenticated response: `RateLimit-Limit`, `RateLimit-Remaining`,
`RateLimit-Reset`. On exceed: `429`, `Retry-After`, problem type
`rate_limit_exceeded`, `budget_exceeded` or `volume_quota_exceeded`. `Cache-Control:
no-store` on authenticated responses containing user data.

---

## 14. Security requirements (all surfaces)

- **Prompt isolation:** any text that is not an operator instruction is delimited data.
  Injection attempts are flagged (`injection_suspected`) and never obeyed. Evidence IDs,
  verdicts, gate results and citations come from validated structures, never free text.
- **SSRF:** for URL inputs and document URLs, resolve the hostname before connecting; block
  private, link-local, loopback and cloud-metadata ranges unless explicitly allowlisted;
  re-check after redirect or refuse redirects into those ranges; cap response size and
  time.
- **Uploads:** media-type and magic-byte validation, size limits, parser isolation, ZIP
  protections, no HTML rendering of user content; filenames are metadata only.
- **Secrets:** API keys, device tokens and provider keys are never logged or returned after
  creation. Provider keys are encrypted at rest. No application container mounts the Docker
  socket.
- **Authorization:** every object access checks ownership/permission server side; 404 is
  used instead of 403 where existence itself is confidential (unapproved documents).
- **TLS** is mandatory for non-loopback deployments and external providers.
- **CSP** on the web app; no inline scripts from documents; `X-Content-Type-Options:
  nosniff`; `Referrer-Policy`; frame denial except the extension's own embedding.
- **Logs** contain request ids, principals (ids), routes, status, latency and usage figures,
  never content, author names, raw prompts or provider keys. Retention applies.

---

## 15. Retention and deletion

| Data | Retention |
| --- | --- |
| Check text and result | indefinite (archive), unless deleted by QS |
| Context metadata (author, URL, platform, post id) | default 90 days, configurable; redacted after expiry |
| Uploaded check file/image and fetched URL body | deleted after the result is produced, at most 24 h |
| Conversation text | user-deletable; default 90 days for chats, claims/anonymised archive remains |
| Document originals and parsed text | as long as the document is approved; kept for backup/restore |
| Usage events | 90 days; hourly/daily summaries indefinite |
| Moderation raw outputs | not stored; only categories/actions |
| Job/event records | 30 days after completion |
| Audit log | 1 year |

Deleting a chat removes the conversation and its messages but keeps checked claims in the
archive with no author, URL or platform. QS deletion of an archive entry is soft-delete
plus an audit entry. A withdrawn document stays in provenance history for past results.

---

## 16. Versioning and compatibility

- `fcp/1` is additive. Unknown fields are ignored; unknown enum values must be treated as
  unknown, not as the nearest known value.
- Breaking changes require `/v2` or a new media type. A deprecation is announced with
  `Deprecation` and `Sunset` headers at least one release before removal.
- Model/prompt/pipeline versions are part of every result. A configuration change does not
  rewrite old results; re-checks create new result versions.
- The OpenAPI document is generated from the backend and committed to `docs/openapi.json`;
  CI fails on drift. The web and extension clients are regenerated from it.
- The public `/v1` surface is the Schemathesis target; `/api` and `/internal` are excluded
  from automatic fuzzing.

---

## 17. Reserved for v2 (not implemented in v1)

The following concepts are named only so that v1 does not accidentally conflict with them.
They have **no v1 endpoints and no v1 behaviour**:

- `GET /v1/instance` remains the only federation-facing endpoint.
- Peer evidence (`POST /v1/evidence/query`), manifest/changes/snapshot and document
  export are v2.
- Sync fields (`origin_instance_id`, `origin_document_id`, `provenance_chain`,
  `redistribution`, change log) are stored in v1.
- Web search, public chat, share links and webhooks are out of scope.
- Tier 2 and tier 3 evidence are reserved; v1 results contain tier 1 only.
