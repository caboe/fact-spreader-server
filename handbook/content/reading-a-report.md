---
title: Reading a report
description: The sections of a claim report, what the evidence shows, and what the warnings mean.
---

A report has five parts: the overall verdict, the statements, the evidence, the warnings
and, when a persona is selected, a narrative. This page explains what each part means.

## The overall verdict

The overall verdict summarises the statement verdicts of the whole input. It is computed
in code from the individual statements, never written by a model. A misleading frame can
drive the overall verdict even when every single sentence is true. The explanation below
the label names the statements and patterns that decided it.

The seven possible values and the exact rules are on the [Verdicts](../verdicts/) page.

## Statements

Each statement appears with the text that was checked and its own verdict. Below the
verdict, the report lists:

- **What is true** — the part of the statement that the evidence supports.
- **What is missing** — context the statement leaves out, such as a relevant comparison,
  a different time period or a confounder that changes the conclusion.
- **What is unverifiable** — parts the approved corpus cannot settle, with the reason.

A statement can be `not_checkable` (for example an opinion or a normative claim) while an
empirical premise inside it is checked separately. The report deliberately does not check
what it cannot decide.

## Evidence

Every evidence item is a passage from an approved document, shown with:

- the identifier used in the statement,
- the publisher and, where available, the publication date,
- the publisher's quality grade,
- the passage itself and a link to the source when one is stored.

The grade describes the **publisher**, not whether the passage supports the statement.
Independence is judged by origin, not by how many links point to it: two reports built on
the same dataset count once.

A report never invents an evidence item. Identifiers that were not part of the retrieved
candidate set are rejected before the report is built.

## Warnings

Warnings explain why a result is weaker than its label suggests, or why a part of the
pipeline was limited. Common warnings:

| Code | What it means |
| --- | --- |
| `stale_evidence` | A decisive source is older than the topic's staleness window. If the claim is about a current state and every decisive source is stale, the verdict is capped at `insufficient_evidence`; the old figure is still shown as context. |
| `audit_incomplete` | A material confounder stayed unresolved after targeted re-retrieval. A clean `true` is not possible in that state. |
| `gate_downgraded` | The evidence did not meet the gate, so the verdict was lowered to `insufficient_evidence`. The reason is recorded. |
| `no_matching_document` | No approved document matched the statement. |
| `quote_context_unavailable` | The original context of a quotation could not be retrieved. The wording alone cannot settle it, so the statement is not reported as `true`. |
| `quote_translated` | A quotation was translated. The report says whether the translation is accurate or distorted; it is never called verbatim. |
| `image_authenticity_not_checked` | Text was read from an image, but the image itself was not checked for manipulation. |
| `preliminary_result` | A fast-mode result is shown before the full check has finished. The full check replaces it as a new version. |
| `consistency_fallback` | The persona narrative did not pass the consistency check and was replaced by the deterministic fallback. |
| `output_moderation_replaced` | The rendered narrative was moderated and replaced. The substance is unaffected. |
| `injection_suspected` | The input contained text aimed at instructing the model. It was treated as data, not followed. |

The full machine-readable list is in
[`PROTOCOL.md` §3.12](https://github.com/caboe/fact-spreader-server/blob/main/PROTOCOL.md).
Clients ignore warning codes they do not know.

## Narrative and substance

The **substance** is deterministic: verdicts, evidence, citations and warnings are the
same regardless of persona and response language. The **narrative** is the readable
explanation. It is generated in full, checked against the substance, and only then shown.
If it fails the check, it is withheld or replaced; the substance is never changed to fit
the narrative.

## Versions

Reports are versioned per claim. A new version is created when:

- a preliminary fast-mode result is replaced by the full check,
- the corpus changed and the claim was re-checked,
- the configuration changed and the claim was re-checked.

The archive lists the newest version of each claim. Opening a claim shows the whole chain,
so an older report remains readable.

## When the corpus has no answer

`insufficient_evidence` means the claim is checkable in principle but the approved corpus
does not settle it. The query is added to the editorial list of corpus gaps, grouped with
similar queries. If you know an approved-quality source that should be covered, submit it
as a document. It becomes citable only after an editor has approved it and indexing has
finished.

Reports also carry a feedback control. Use it when a citation does not support its
statement or when a relevant document is missing; it feeds the editorial review.
