# Evaluation test sets

IMPLEMENT Phase 4 and Phase 11 define several sets. This directory holds the
parts that exist.

## `reference_corpus.yaml` (layer B)

A **manifest only**. The documents themselves are downloaded locally with
`make fetch-reference-corpus` (`backend/app/tools/fetch_reference_corpus.py`) and
are not committed, because they belong to their publishers. The fetcher writes a
`*.meta.json` sidecar per document with the licence, URL and content hash, so an
ingestion run can use that metadata directly.

Every entry currently has an empty `license`, which makes the fetcher refuse it.
That is deliberate: the operator is responsible for correct license metadata
(PURPOSE §3.6), and the candidate list in IMPLEMENT Phase 4 has to be checked
against current editions before the corpus is usable. Fill in `license` (and
`sha256`, if you want the fetch verified) entry by entry as you verify them.

## `claims.seed.jsonl` (not written yet)

IMPLEMENT Phase 4 requires the two canonical cases plus at least twenty labeled
claims across all six verdicts, including normative, adversarial-nonsense,
quote-context and stale-evidence cases. It does not exist yet, so
`make eval` exits with code 2 and says so rather than producing a meaningless
score.

The format `backend/app/tools/eval_runner.py` expects is one JSON object per
line:

```json
{"id": "hours-de-1", "text": "Average weekly working hours in Germany are particularly low.", "expected_verdict": "true_but_misleading", "domain": "economics", "cross_lingual": false, "note": "part-time composition effect"}
```

## Predictions file (for the baseline gate)

`--predictions` scores recorded pipeline outputs, which is the "recorded
responses" baseline gate from IMPLEMENT Phase 11. One JSON object per line:

```json
{"id": "hours-de-1", "verdict": "true_but_misleading", "gate_downgraded": false, "consistency_fallback": false}
```

`make eval` prints per-verdict precision/recall, macro-F1, misleadingness
detection recall, the gate-downgrade rate and the consistency-fallback rate.
