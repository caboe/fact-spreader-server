# Fact Spreader — server

A fact-check and research service over a curated, editorially approved knowledge base.
It verifies the factual core of a claim, audits what the claim leaves out and how it
frames it, and returns a structured verdict with citations. The defining case is the
**formally true but misleading** claim. Browser extension:
[fact-spreaders/fact-spreader](https://github.com/fact-spreaders/fact-spreader).

## Status

**Planning — specs revised, implementation plan awaiting human approval.** No application
code has been written yet. The specs below were revised for the v1 scope on 2026-11-16
using [`docs/REDESIGN_NOTES_DE.md`](docs/REDESIGN_NOTES_DE.md) as the decision log; the
build plan is [`IMPLEMENT.md`](IMPLEMENT.md), whose Phase 1 is a vertical slice through
stock LightRAG and a real model.

| Path | What | State |
| --- | --- | --- |
| [`PURPOSE.md`](PURPOSE.md), [`PROTOCOL.md`](PROTOCOL.md), [`PERSONAS.md`](PERSONAS.md) | Requirements, wire contracts, personas and rendering | Revised for v1 on 2026-11-16 |
| [`IMPLEMENT.md`](IMPLEMENT.md) | Phases and `[agent]`/`[human]` checks | Proposed; awaiting human approval and the live-model budget |
| `methodology/` | Publisher grades, confounder checklists, argument patterns | Unchanged copy; valid and referenced by the new specs |
| [`docs/SOURCE_GRADING.md`](docs/SOURCE_GRADING.md) | Grading criteria for `methodology/publishers.json` | Unchanged copy; path corrected |
| `tests/eval/` | Hand-labelled claim and moderation sets, reference-corpus manifest | Carried over; `claims.seed.jsonl` currently has duplicate ids and repeated rows and is repaired in Phase 9 |
| `tests/fixtures/corpus/` | Synthetic CI corpus (19 documents, labelled `FIXTURE — not a real source`) | Unchanged copy with front matter |

## Next step

Approve [`IMPLEMENT.md`](IMPLEMENT.md) and set the live-model budget (§2). Phase 1 then
starts with the repository scaffold and the vertical slice.

## Licences

* Code: [GNU AGPL-3.0-or-later](LICENSE).
* Methodology data, personas, evaluation sets and the fixture corpus
  (`methodology/`, `PERSONAS.md`, `tests/eval/`, `tests/fixtures/corpus/`):
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
* Contributions are accepted under the
  [Developer Certificate of Origin](https://developercertificate.org/): sign off your
  commits (`git commit -s`).
