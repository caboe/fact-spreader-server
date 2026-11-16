# Evaluation test sets

IMPLEMENT Phase 9 defines the runner and the final sets. This directory holds the
carried-over material from the first implementation.

## `reference_corpus.yaml` (layer B)

A **manifest only**. The documents themselves are downloaded locally with
`make fetch-reference-corpus` (the fetcher is built in Phase 9) and are not committed,
because they belong to their publishers. The fetcher writes a `*.meta.json` sidecar per
document with the license, URL and content hash, so an ingestion run can use that metadata
directly.

Every entry currently has an empty `license`, which makes the fetcher refuse it. That is
deliberate: the operator is responsible for correct license metadata (PURPOSE §3.4), and
the candidate list must be checked against current editions before the corpus is usable.
Fill in `license` (and `sha256`, if you want the fetch verified) entry by entry as you
verify them.

## `claims.seed.jsonl` (carried over, needs repair)

The file exists but is **not usable yet**: it has duplicate ids, several distinct claim
texts reusing the same id and repeated rows. IMPLEMENT Phase 9 repairs the ids and rows and
re-labels the expected verdicts against the fixture corpus for the one-source gate and the
new `contested` verdict. Until then, `make eval` is not expected to run.

The format the runner will use is one JSON object per line:

```json
{"id": "hours-de-1", "text": "Average weekly working hours in Germany are particularly low.", "expected_verdict": "true_but_misleading", "domain": "economics", "cross_lingual": false, "quote_context": false, "stale": false, "injection": false, "note": "part-time composition effect"}
```

## Predictions file (for the baseline gate)

`--predictions` scores recorded pipeline outputs, which is the "recorded responses"
baseline gate from IMPLEMENT Phase 9. One JSON object per line:

```json
{"id": "hours-de-1", "verdict": "true_but_misleading", "gate_downgraded": false, "consistency_fallback": false}
```

`make eval-recorded` prints per-verdict precision/recall, macro-F1, misleadingness
detection recall, the gate-downgrade rate and the consistency-fallback rate.
