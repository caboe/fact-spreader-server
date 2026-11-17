# Phase 3 report — audit depth, contradictions, research and fast mode

Date: 2026-11-17. Stack: Docker Compose, backend/worker built from the Phase 3 tree,
stock LightRAG v1.5.0 with extract/keyword/query bound to the gateway, Postgres with
pgvector + AGE, Redis. Live calls used DeepSeek `deepseek-flash` through the gateway, local
Ollama `bge-m3` embeddings and the existing vision provider. Spend at the end of the run:
**USD 0.638715** of USD 15.00; 70 checks and 77 stored result versions.

## Live acceptance

### Contradiction between approved documents

Two new synthetic fixtures state incompatible 2024 figures for the same measure
(`crime-contradiction-a` supports 5,200 per 100,000; `crime-contradiction-b` refutes it
with 3,900). Both were approved and indexed through the explicit fixture CLI (nine indexed
documents in total).

Claim: *In 2024, the recorded suspect rate for non-citizens was 5,200 per 100,000
residents.*

- Job `job_01M7MJHE036JEMB25V7YWZJXD7`, result `fc_01M7MJHEJNDCE66FRZBPYK6215`, 34.8 s.
- `overall_verdict = contested`.
- Statement gate: `independent_sources = 7`, not downgraded.
- Contradiction `ctr_01M7MJJHAYVDMDXF2FHYFT696S`: supporting `E1` (BKA, 2025-02-10),
  refuting `E2` (Example Statistical Office, 2025-03-04), `scope_comparison =
  same_period`.
- The German methodology passage (`E8`) was returned with a machine translation labelled
  `passage_translation.language = en`; the original remains authoritative.

### Stale evidence

New fixture `crime-stale-figure` (published 2016) states a 2015 figure that no other
approved document carries.

Claim: *The recorded suspect rate for non-citizens is 7,100 per 100,000 residents.*

- Job `job_01M7MJHPGMQ2NDZMXN72AJQ05N`, result `fc_01M7MJJQZ3R7Z988032MN3ZFB7`, 31.8 s.
- `overall_verdict = insufficient_evidence`.
- Gate `downgraded = true`, `reason = stale_evidence`; warnings `stale_evidence` and
  `audit_incomplete`; no `true`.

### Cross-lingual decisive evidence

New German-only fixture `crime-german-only` states the only figure for the claim.

Claim: *Police recorded 1,234 home burglaries in Germany in 2024.*

- Job `job_01M7MJVXSNZ1HPMFVTXQFT53QW`, result `fc_01M7MJVYQ7GGTP9DY0J31281JB`, 16.6 s.
- `overall_verdict = true`, no warnings.
- The only evidence is `E1`, the German BKA fixture; its `passage_translation` is `en` and
  machine-labelled, while the German passage remains authoritative.

### Research summary

`POST /v1/search` with `summary=true` returned five documents and a summary in 17.0 s.
`consistency.checks = [citation_ids, every_sentence_cited, metadata_quotation_limit,
judge_support]`; the independent `fs-verify` judge passed on the first attempt. A forced
inconsistency path is covered by the integration test that returns `summary=null` and
`summary_consistency_failed`.

### Fast mode and versioning

| Measurement | Samples | Result |
| --- | --- | ---: |
| Cache hit, workers idle | 1.33 / 1.66 / 1.70 s | p50 1.66 s, p95 1.70 s |
| Cache hit, eight full jobs competing | 4.57 / 5.65 / 5.65 / 5.86 / 6.27 s | p50 5.65 s under provider contention |
| Cold preliminary | 3.48 / 3.63 / 4.82 s (first run 9.6 s) | p50 3.63 s, p95 4.82 s |
| Full check after fast | 18.4 / 19.6 / 20.0 / 24.6 / 45.6 / 50.8 / 62.2 / 81.8 s | p50 35.1 s, p95 81.8 s |

Cache hits meet the < 2 s target when the provider is not saturated. The 5–6 s samples are
recorded rather than hidden: they occurred while eight full checks were running against the
same remote provider. The fast path itself does not wait for the full check.

Cold run `fc_01M7MJ6QXSDNVWZJVVHVXCDV1X` returned two statements with `preliminary=true`
and a null verdict in 9.6 s; its full result `fc_01M7MJ6RVW8R98BDJT6JPS4Z2R` is version 2
with `previous_version_id` set and `true_but_misleading`. A later hit returned the gated
verdict as a preliminary with `X-Full-Result-Job`. The archive listed only the current
version; the detail returned `[(1, preliminary), (2, full, current)]`.

### Re-check and deletion

The integration test re-checks a stored claim, asserts `previous_result_id`, the `recheck`
payload flag and version 2, then deletes the chain with `quality:read`: both versions are
soft-deleted, the archive returns 404 and an `audit_log` entry is written.

## Automated checks

`make verify` is green: **63 unit tests, 30 integration tests**, formatting, lint, strict
mypy, Alembic up/down/up and drift, OpenAPI drift and compose policy. The new integration
tests cover the semantic cache hit, fast preliminary versioning, OpenAI fast and streaming,
archive version chains, re-check and soft deletion.

## Re-retrieval

The targeted re-retrieval path is covered by the integration suite: one test fills an open
confounder with a second retrieval and a second verification; the other leaves the gap
unfilled and asserts `insufficient_evidence` with `audit_incomplete`, never `true`. The
live corpus did not produce an open-confounder claim in the acceptance run, so this remains
an integration check rather than a live claim.

## Open items

- Automatic re-check on a corpus-change event is not wired yet; the manual re-check path
  and its daily budget are in place. Phase 4 produces the document event.
- Semantic duplicate detection for rephrased submissions is served by the fast cache but
  does not yet add a `duplicate_suspected` warning to archive entries.
- The contradiction/staleness fixtures are synthetic and stay in `tests/fixtures/corpus/`;
  they are seeded only by the explicit approval CLI.
