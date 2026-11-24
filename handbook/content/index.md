---
title: Fact Spreader handbook
description: What Fact Spreader does, what a check returns, and where to start reading.
---

Fact Spreader checks the factual core of a claim. It verifies the claim against a curated
corpus of editorially approved documents, audits what the claim leaves out, and returns a
verdict with citations. It is built for the case where a statement is formally true but
misleading.

The service runs on your own instance. Every answer depends on the documents that instance
has approved and indexed. Fact Spreader does not search the open web for evidence.

## Three things you can do

| Task | You give it | You get |
| --- | --- | --- |
| **Check** | a claim or a passage, as text, file, URL or image | a report with each statement, its verdict, what is true, what is missing, and evidence |
| **Research** | a topic | approved documents and passages, previously checked claims, and an optional cited summary |
| **Submit a document** | a file, a URL or a batch | a document for the editorial queue; it becomes citable only after approval and indexing |

## Start here

- [Checking a claim](./checking-a-claim/) explains the inputs, what happens during a check
  and what fast mode changes.
- [Reading a report](./reading-a-report/) walks through the sections of a report and the
  warnings it can carry.
- [Verdicts](./verdicts/) defines the seven verdict values and the rules behind them.

## What makes Fact Spreader different

- **The verdict is computed in code.** A model proposes a verdict per statement, but the
  gate, the overall verdict and contradiction detection are deterministic functions over
  the evidence. A model never writes the final label.
- **Evidence is cited, never invented.** Every evidence identifier in a report must exist
  in the retrieved candidate set; anything else is rejected.
- **Leaving things out is part of the check.** The misleadingness audit looks for
  confounders a claim omits, and the report names what is missing instead of stopping at
  the literal wording.
- **Only approved documents count.** Claim text, research queries and uploaded files never
  enter the corpus. An editor approves every citable document first.
- **The substance is stable.** Verdicts, evidence, citations and warnings do not change
  with the chosen persona or response language. Only the narrative does.

## If you are operating an instance

The handbook covers the user-facing workflows first. Operator topics, such as the setup
wizard, providers and models, budgets, retention and backup, are documented in the
repository under `docs/` and will be added to this handbook as a separate section.
