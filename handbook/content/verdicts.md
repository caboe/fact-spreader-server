---
title: Verdicts
description: The seven verdict values, how the overall verdict is computed, and when a verdict is downgraded.
---

A verdict is a structured label over evidence. It is not a truth score and not a
probability. Fact Spreader has seven values, and each one answers a different question.

## The seven values

| Verdict | Meaning |
| --- | --- |
| `true` | Accurate as stated and not materially misleading. |
| `true_but_misleading` | The empirical core is accurate, but essential context is missing and the implied conclusion does not follow. |
| `partially_false` | Some material parts are accurate, others are false. |
| `false` | Contradicted by the evidence. |
| `contested` | Approved sources support **and** refute the same statement over the same period. |
| `insufficient_evidence` | Checkable in principle, but the approved corpus does not settle it. Also the target of every gate downgrade and of an unfinished audit. |
| `not_checkable` | Normative, predictive, counterfactual, motivational or otherwise unfalsifiable. Empirical premises inside it are still checked separately. |

The first five values pass the gate described below before they are shown. The last two do
not need it: `insufficient_evidence` is where a failed gate lands, and `not_checkable`
means there is no factual claim to gate.

`contested` is not a synonym for `insufficient_evidence`: with `contested`, the corpus
contains both positions and both are cited. With `insufficient_evidence`, the corpus does
not contain enough to decide either way.

## The overall verdict

The overall verdict is a deterministic function of the statement verdicts. It is never
produced by a model. Given the statements of one report:

1. Ignore `not_checkable` statements and statements that are not checkworthy.
2. If nothing remains, the overall verdict is `not_checkable`.
3. If any remaining statement is `contested`, the overall verdict is `contested`.
4. If all remaining statements are `insufficient_evidence`, the overall verdict is
   `insufficient_evidence`.
5. If any is `false` and none is accurate, the overall verdict is `false`.
6. If any is `false` or `partially_false` and at least one is accurate, the overall verdict
   is `partially_false`.
7. Otherwise, if any is `true_but_misleading`, the overall verdict is
   `true_but_misleading`.
8. Otherwise, the overall verdict is `true`.

"Accurate" here covers `true`, `true_but_misleading` and `partially_false`. Because of step
7, a text can carry `true_but_misleading` even when every individual statement is true: the
frame, not a single sentence, is the problem.

## The gate

Every truth-bearing verdict (`true`, `true_but_misleading`, `partially_false`, `false`,
`contested`) passes a gate in code before it is shown:

- at least a configured number of **independent** sources (default: one, because approved
  documents count as true) at or above a configured publisher-grade threshold (default:
  grade B);
- for `true_but_misleading`, every item in "what is missing" needs at least one qualifying
  source; a missing context that no source supports cannot be asserted;
- for `partially_false`, the accurate and the false parts are gated separately.

If the gate fails, the verdict becomes `insufficient_evidence`, the report records
`gate.downgraded` and the reason.

Independence is judged by origin. A DOI, otherwise the canonical URL, otherwise publisher,
title and publication date, identifies a source. Two reports on the same dataset count
once, however many links exist.

## Why a verdict can be downgraded

A strong-looking claim can end as `insufficient_evidence` for reasons that are about the
corpus, not the claim:

- **Open confounder.** The audit found a material confounder it could not resolve after
  targeted re-retrieval. A clean `true` is not allowed while `audit_incomplete` stands.
- **Stale evidence.** If the claim is about a current state and every decisive source is
  older than the topic's staleness window, the verdict is capped at
  `insufficient_evidence`. The old value is still shown as context ("true for 2019"), but
  it does not settle "today".
- **Quote without context.** Verifying the wording of a quotation is not enough. If the
  original context cannot be retrieved, the quotation is not reported as `true`.
- **No matching document.** If no approved document matches, the verdict is
  `insufficient_evidence` and the query is recorded as a corpus gap.

## Contradiction or development

If one approved document supports a statement and another refutes the same statement over
the same period, the verdict is `contested` and both bodies of evidence are shown. This is
a property of the corpus, and it is logged for editorial review.

If the two documents cover different, non-overlapping periods, this is a development, not
a contradiction. The source that matches the claim's period wins. If the claim has no
period, the most recent source wins and the older one is shown as historical context.

## What a verdict is not

- **Not a probability.** `true` does not mean "95% likely".
- **Not a model opinion.** The model proposes; the gate and the overall verdict decide.
- **Not a statement about the open web.** It is a statement about the approved corpus at
  the time of the check.
- **Not permanent.** A re-check after a corpus or configuration change creates a new
  version and can reach a different verdict.

If a verdict surprises you, read the evidence and the warnings first. A missing citation, a
stale source or an open confounder explains most disagreements about the label.
