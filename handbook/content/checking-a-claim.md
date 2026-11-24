---
title: Checking a claim
description: What you can submit, how a check runs, and what fast mode changes.
---

A check takes a claim or a passage, splits it into statements, and verifies each statement
against the approved corpus. The result is a [report](../reading-a-report/) that shows what
is true, what is missing and what cannot be settled.

## What you can submit

| Input | How it is read |
| --- | --- |
| **Text** | Pasted text. Every checkworthy statement is extracted separately, with its exact position in the text. |
| **File** | PDF, DOCX, HTML, Markdown or plain text. Tables in HTML and digital PDFs are converted; figures in PDFs get a vision-generated description. |
| **URL** | The page is fetched once and the text is extracted. The fetch is guarded against internal addresses. |
| **Image** | Visible text is read by a vision model. The check does not verify whether the image itself is authentic or manipulated. |

Instance limits apply to the amount of text, the file size and the number of files in a
batch. The input form shows the limits that are configured for your instance.

Submitting a check never writes to the corpus. Your text, the uploaded file and the fetched
page stay outside the knowledge base.

## How a check runs

1. **Input moderation.** The input is classified before anything else. Most findings only
   flag the check; sexual content involving minors is always blocked.
2. **Statement extraction.** Statements are extracted with their span, their kind (fact,
   opinion, rhetoric, implied conclusion, normative) and a checkworthiness judgement.
   Opinions and normative statements are marked `not_checkable`, but empirical premises
   inside them are extracted separately.
3. **Scope.** Subject, place, period, population and quoted source are identified. If a
   missing place or period would change the answer, the pipeline asks a clarification
   question instead of guessing. Answering it resumes the check.
4. **Retrieval.** A hybrid graph and vector search over approved documents returns evidence
   candidates with provenance. Only approved documents are searched.
5. **Verification.** A structured model call proposes a stance for each candidate
   (`supports`, `refutes`, `context`, `mixed`) and a verdict per statement. The backend
   rejects evidence identifiers that are not in the candidate set.
6. **Misleadingness audit.** Topic-specific confounder checklists are applied. For every
   unaddressed confounder, the pipeline runs a targeted re-retrieval, at most twice. If a
   material confounder stays open, a clean `true` is not possible.
7. **Argument analysis.** Known argument patterns, such as omitted confounders or base-rate
   neglect, are labelled only when the evidence supports the label and the report explains
   the mechanism.
8. **Gate and overall verdict.** Both run in code. See [Verdicts](../verdicts/) for the
   rules.

The deterministic part of the report is streamed as soon as it is ready. A persona
narrative is written in full, checked against the substance, and only then sent. If the
narrative fails the consistency check, it is replaced by a deterministic template, so the
report always carries a readable narrative and the substance never changes.

## Fast mode

Fast mode is the quick path used by the browser extension:

- A semantic cache hit over previously checked claims can answer in under two seconds.
- Otherwise a reduced pipeline returns a **preliminary** result in under fifteen seconds.
  The full check follows automatically in the background and replaces the preliminary
  result as a new version.
- A preliminary result is always marked. A clean `true` is never returned while the audit
  has open confounders.

The full gate still applies. Fast mode changes how quickly a result appears, not how strict
it is.

## Language and persona

The deterministic substance is available in English, German, French and Spanish. If the
input language is unsupported, the check falls back to English and says so.

A persona changes the narrative, not the substance. The analyst, the mediator and the
straight-talker receive the same verdicts, evidence and citations; only tone, length and
explanation style differ.

## Practical tips

- **Keep the scope in the text.** If the claim refers to a particular year, country or
  group, leave that wording in. It decides which evidence is relevant.
- **Check a quotation for context, not just wording.** A quotation is never reported as
  verbatim from its wording alone. The original context is retrieved; a translation is
  reported as accurately rendered or distorted.
- **Expect several statements.** A longer passage is split into statements and each one
  gets its own verdict. The overall verdict is computed from them, so a true sentence in a
  misleading frame can still produce `true_but_misleading`.
- **A check is not a search.** If the corpus has nothing on the subject, the report says
  `insufficient_evidence`. That is a statement about the corpus, not about the claim.
  Submit a source document if you know one that should be covered.
