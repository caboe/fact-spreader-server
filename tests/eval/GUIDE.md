# Labeling guide

How a claim in `claims.seed.jsonl` is labeled, and what the label means. The guide exists
because the labels are the measurement: a set labeled to fit the pipeline's output measures
nothing.

## The one rule

**Label against the fixture corpus, not against the world.** Every expectation is a
statement about what the documents in `tests/fixtures/corpus/` support. A claim that is
true in reality but unsupported by that corpus is labeled as the corpus sees it, and the
`note` says why.

That is what makes the set usable without a live model, and it is also its limit: the
numbers measure the pipeline's handling of *these* documents, not its factual accuracy in
general. `docs/EVALUATION.md` (Phase 9) says so where the metrics are reported.

## The verdicts

| Verdict | Use it when |
| --- | --- |
| `true` | The corpus supports the claim as stated, including its scope and its units, and the audit finds no material missing context. |
| `true_but_misleading` | Something in the claim is supported, and the claim's **use** of it misleads: a raw comparison read as a cause, an aggregate read as a per-person fact, a suspect statistic read as a conviction. This is the largest category on purpose — it is the failure the project exists to address. |
| `partially_false` | The direction is supported and a number, scope or quantifier is not. |
| `false` | The corpus contradicts the claim, or the claim asserts something the decisive document explicitly denies. |
| `contested` | Two approved documents support and refute the same statement over the same time scope. The claim is not "unknown"; the corpus contains both positions. |
| `insufficient_evidence` | The corpus is silent, the audit cannot be completed, or the gate has no qualifying source. **Not** the same as `not_checkable`: this is an empirical claim that would be checkable with the right document. |
| `not_checkable` | The sentence is normative, about motive, or otherwise not an empirical claim at all. |

The distinction between the last two is the one most often gotten wrong. "The 2026
revision changed the rules again" is `insufficient_evidence` (empirical, just not in this
corpus). "Immigration policy is a failure" is `not_checkable` (no empirical content to
check).

## The flags

* `cross_lingual: true` — the claim is in English (or the decisive passage is German),
  and the evidence that settles it is **only** in the German documents. These measure
  cross-lingual retrieval, which is where a German-language instance earns its keep.
* `quote_context: true` — the claim quotes a source. The label is about whether the
  quotation is used in its original context.
* `stale: true` — the decisive document is old enough that its recording rules or
  definitions have since changed.
* `injection: true` — the text contains an instruction addressed at the model. The
  expected verdict is the one the **evidence** supports; the text must not change it.

## Adding a case

1. Check the claim against the corpus first, and cite the document in `note`.
2. Pick the verdict by the table above, not by what the pipeline currently returns.
3. Set the flags that apply; a case may carry more than one.
4. Run `make eval-recorded` (built in Phase 9). A coverage gap is a hard failure.
5. If a case is ambiguous, say so in `note` rather than choosing silently. An
   honestly-ambiguous case that is later re-labeled is worth more than a confident one
   that hides the ambiguity.
