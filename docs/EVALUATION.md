# Evaluation

The evaluation is a measurement, not a demo. It compares the pipeline's verdict with a
label that was assigned against `tests/fixtures/corpus/`, never against the world. A claim
that is true in reality but unsupported by the fixture corpus is labelled as the corpus
sees it. The numbers therefore describe how this pipeline handles these documents; they are
not a statement about its factual accuracy in general.

## The set

`tests/eval/claims.jsonl` has one JSON object per line:

```json
{"id": "claim-001", "domain": "racism", "expected_verdict": "true_but_misleading",
 "text": "…", "flags": [], "note": "…"}
```

Rules (`tests/eval/GUIDE.md`):

- unique ids, no repeated rows;
- all seven verdicts (`true`, `true_but_misleading`, `partially_false`, `false`,
  `contested`, `insufficient_evidence`, `not_checkable`);
- at least one case for each required flag: `cross_lingual`, `quote_context`, `stale`,
  `injection`;
- at least 24 cases.

`make eval-check` enforces the coverage and fails on a duplicate id, an unknown verdict, a
missing verdict or a missing flag. `tests/eval/moderation.jsonl` is the separate moderation
set: `must` is `pass`, `flag_only` or `block`.

The carried-over seed set had 136 rows with duplicated ids and the same 43 texts repeated
four times, and it had no `contested` case and no flags. It was repaired in Phase 9 to 25
unique cases (from 49 repaired candidates; the rest were kept only as a candidate pool and
removed to keep the live run inside budget): all seven verdicts, the four flags, a
contradiction case, a German-only cross-lingual case, a quote-context case, two stale cases
and two injection cases. A
table/figure-only case could not be added because the fixture corpus contains no table or
figure document; that is a known limitation of this set. The moderation set was
deduplicated from 135 rows to 30 unique cases.

## Runner

```bash
make eval-check       # coverage only
make eval-recorded    # offline: replay tests/eval/predictions.baseline.jsonl
make eval-live        # live: real checks, rewrites the predictions baseline
```

`make eval-live` needs `EVAL_API_KEY_FILE` (default `.local/eval-api-key`, git-ignored):

```bash
docker compose exec -T backend python -m app.cli create-api-key \
  --email operator@fact-spreader.local --name eval-live > .local/eval-api-key
make eval-live
```

Live mode submits each claim with `fast: true`, polls the job, and records one prediction
per case: predicted verdict, result id, latency, preliminary flag, gate downgrade,
rendering/consistency fallback and the per-check cost share. It refuses to score if a job
fails or if the prediction file misses a case. The cost share comes from the
`/v1/usage/summary` delta around the run, so it is an average, not a per-request ledger.

Offline mode requires no network and no model. It refuses an empty predictions file or a
missing case instead of silently scoring a subset.

## Baseline

`tests/eval/predictions.baseline.jsonl` was recorded on 2026-11-18 against a stack seeded
with `tests/fixtures/corpus`. The claims quote and paraphrase those fixture documents by
name and content, so a live run on a stack that does not hold them — for example one with
only the imported dpa corpus — cannot reproduce the labelled verdicts, whatever the
retrieval settings are. Compare a threshold or a model change only on a stack seeded with
`make seed-fixtures`, and regenerate the baseline there.

A single run is noisy. On a fresh fixture stack with an unchanged LightRAG index, three
full runs of the same code scored 0.560, 0.640 and 0.720. Compare configurations by
several runs on the same index, per claim, not by one accuracy figure. A disposable
project for that is a second Compose project with its own ports and volumes (see
`scripts/clean-start-test.sh` for the override pattern), bootstrapped with
`python -m app.cli bootstrap` and seeded with `python -m app.cli seed-fixtures --approve`;
the eval runner takes `--base-url` and `--api-key-file` for it. The relevance-cut
comparison in DECISIONS.md D68 was measured that way.

## Metrics

- accuracy over all cases;
- per-verdict precision, recall and F1, and macro-F1 over the seven verdicts;
- misleadingness recall (recall for `true_but_misleading`);
- gate-downgrade rate (share of results with any downgraded statement);
- consistency-fallback rate over results that have a rendering (n/a in fast mode);
- latency p50/p95;
- cache-hit rate: the share of checks under 1.5 s, a documented proxy because the API does
  not expose a cache flag;
- total cost and cost per check.

The live run uses fast mode. Full-pipeline latency was measured separately in Phase 3
(p50 35.1 s, p95 81.8 s); the fast path is the one the evaluation can run across the whole
set within the budget.

## Baseline (2026-11-18)

The fixture corpus was seeded in full (23 documents) and the 25 cases were run through the
full pipeline. The recorded predictions are `tests/eval/predictions.baseline.jsonl`;
`make eval-recorded` reproduces these numbers without a network:

| Metric | Value |
| --- | --- |
| Cases | 25 |
| No verdict | 0 |
| Accuracy | 0.640 |
| Macro-F1 (7 verdicts) | 0.625 |
| Misleadingness recall | 0.333 |
| True precision / recall | 1.000 / 0.833 |
| True-but-misleading precision / recall | 0.667 / 0.333 |
| False precision / recall | 1.000 / 1.000 |
| Contested precision / recall | 0.500 / 1.000 |
| Gate-downgrade rate | 0.160 |
| Latency p50 / p95 | 16.3 s / 71.2 s |
| Cache-hit rate (<1.5 s) | 0.000 |
| Cost | $0.0812 ($0.003248/check) |

The set is small and the numbers describe this synthetic corpus. Two pipeline issues were
found while producing them and fixed before the baseline: retrieval ignored a document-level
source-quality override (all fixture evidence was graded D), and verification output hit the
8k-token cap on longer evidence sets (candidates are now capped at six with a compact-output
instruction). Re-running `make eval-live` overwrites the baseline; review the diff before
committing it.
