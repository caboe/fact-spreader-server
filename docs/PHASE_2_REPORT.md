# Phase 2 report — inputs, streaming and the OpenAI surface

Date: 2026-11-17. Stack: Docker Compose on the local machine, backend/worker image
`factspreader/backend:0.1.0` built from commit `f79bd45`; LightRAG
`ghcr.io/hkuds/lightrag:v1.5.0` (stock, keyword role bound to the gateway in `ec1f3f3`);
Postgres with pgvector + AGE; Redis. Live model calls went through the internal gateway to
DeepSeek `deepseek-flash` (chat, extraction, verification, audit, moderation), local Ollama
`bge-m3` for embeddings, and OpenRouter `google/gemini-2.5-flash` for `fs-vision`. Regular
tests used fakes only.

Spend at the end of the phase: **USD 0.515888** of the approved USD 15.00 (53 checks and
47 stored results in the instance). The hard stop was not approached.

## What ran

| Check | Observed |
| --- | --- |
| Plain text | `POST /v1/factcheck` with the canonical claim completed with `true_but_misleading`, six tier-1 A-grade evidence items, gate `independent_sources = 4`, `downgraded = false`; two checkworthy statements with spans on the input. |
| PDF upload | multipart `claim.pdf` stored as `input.type = file`, `media_type = application/pdf`, result `fc_01M7MDWHQ4N1KM5SB4Z5Q7BKCY`, status complete; the extracted text was checked, not indexed. |
| Markdown upload | `upload-check.md` stored as `input.type = file`, `media_type = text/markdown`, result `fc_01M7MCRAWK0N9SK157PYFSBPEY`. |
| URL | `https://example.com` fetched through the SSRF-guarded reader, stored as `input.type = url`; the page had no matching approved passage, so the verdict was `insufficient_evidence`, not a guess. |
| Image | `claim-screenshot.png` went through the vision path, stored as `input.type = image`, result `fc_01M7MDHMTV2HJ1D67NB22FV6F7`, `true_but_misleading`, warning `image_authenticity_not_checked`. |
| SSRF guard | A URL pointing at a private/loopback address is rejected before the fetch; covered by the SSRF test suite (`make verify`). |
| Size limits | Oversized uploads return `413 payload_too_large`; covered by the integration tests. |
| SSE | A live stream produced `state`, two `statement` events, `result` and `done` with monotonic IDs 1–2 (`.local/live-sse.txt`). Statements are durable and replayable with `Last-Event-ID`; the integration suite exercises replay and queued cancellation. |
| OpenAI checked streaming | `.local/openai-stream.txt`: keepalive comments while the pipeline ran, then a first `chat.completion.chunk` carrying the full substance, content deltas only after the consistency check, and `data: [DONE]`; 25 data events. |
| OpenAI error shape | Unsupported parameters return the OpenAI error object, not the native problem document; covered by `tests/integration/test_openai.py`. |
| Device token | A token restricted to `claims:submit` returned `GET /v1/models` with 200; after revocation the same token returned 401. Archive feedback `helpful` was stored and surfaced as `helpful = 1`. |
| Moderation | Explicit sexual content involving minors is refused before a check; other categories flag and continue, including the discriminatory canonical claim. |

## Persona × language matrix

Twelve live runs through `POST /v1/chat/completions` (`model = factcheck:<persona>`) on the
canonical claim, one per persona and response language. All twelve returned
`format = persona`, `consistency.passed = true` on the first judge attempt, no warnings and
`overall_verdict = true_but_misleading`. The Analyst's `no_second_person` mechanical check
passed in en, de, fr and es.

| Persona | Language | Seconds |
| --- | --- | ---: |
| analyst | en | 85.9 |
| analyst | de | 54.6 |
| analyst | fr | 68.6 |
| analyst | es | 53.8 |
| mediator | en | 148.6 |
| mediator | de | 90.7 |
| mediator | fr | 147.4 |
| mediator | es | 66.6 |
| straight-talker | en | 56.1 |
| straight-talker | de | 103.3 |
| straight-talker | fr | 57.6 |
| straight-talker | es | 68.0 |

Median 68.3 s; slowest 148.6 s. These are full-pipeline plus persona rendering and judge
latencies, not the Phase 3 fast target.

The first German Analyst run fell back to the template because output moderation flagged
the narrative as `discriminatory_generalization`, although it had passed the deterministic
checks and the judge. The classifier was reacting to the topic, not to an assertion; the
English run passed. The output-moderation prompt now distinguishes attributing or refuting
a claim from asserting it (`f79bd45`), and the German rerun passed in 54.6 s. The narrative
is still replaced on any hit; the sexual-minors hard floor is unchanged.

The research slice was also exercised live after Phase 2: `/v1/search` returned five
documents and a fully cited summary whose judge check passed, in 17.0 s. It is recorded
under Phase 3.

## Automated checks

`make verify` is green at `28ee94a`: formatting, lint, strict mypy, **63 unit tests**,
**26 integration tests**, the Alembic up/down/up and drift check, the OpenAPI drift check,
and the compose policy check. Live calls are not part of the regular suite.

## Notes for the next phase

- Fast mode, the semantic cache and the full re-check archive flow are not implemented;
  `fast=true` still returns `503 fast_mode_not_available`.
- Phase 3 targeted re-retrieval is implemented and tested; its live acceptance run is
  still open.
- No application UI exists yet, so there are no screenshots; visual acceptance starts in
  Phase 7.
- Phase 2 has no `[human]` checkpoint, so it is complete with this report.
