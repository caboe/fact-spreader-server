# Fact Spreader — server

A fact-check and research service over a curated, editorially approved knowledge base.
It verifies the factual core of a claim, audits what the claim leaves out and how it
frames it, and returns a structured verdict with citations. The defining case is the
**formally true but misleading** claim. Browser extension:
[fact-spreaders/fact-spreader](https://github.com/fact-spreaders/fact-spreader).

## Status

**Planning.** There is no code yet. This repository is a fresh start after a first
implementation; the decisions for the redesign are recorded (in German) in
[`docs/REDESIGN_NOTES_DE.md`](docs/REDESIGN_NOTES_DE.md).

Carried over from the first implementation, to be revised:

| Path | What | State |
| --- | --- | --- |
| `PURPOSE.md`, `PROTOCOL.md`, `PERSONAS.md` | Requirements, wire contracts, personas | Unchanged copies; to be revised per §11 of the redesign notes |
| `methodology/` | Publisher grades, confounder checklists, argument patterns | Unchanged copies |
| `docs/SOURCE_GRADING.md` | Grading criteria for `methodology/publishers.json` | Unchanged copy |
| `tests/eval/` | Hand-labelled claim and moderation sets, reference-corpus manifest | Unchanged copies; expected verdicts must be re-labelled for the revised gate and the new `contested` verdict |
| `tests/fixtures/corpus/` | Synthetic CI corpus (19 documents, labelled `FIXTURE — not a real source`) | Exported from Python to Markdown with front matter |

## Licences

* Code: [GNU AGPL-3.0-or-later](LICENSE).
* Methodology data, personas, evaluation sets and the fixture corpus
  (`methodology/`, `PERSONAS.md`, `tests/eval/`, `tests/fixtures/corpus/`):
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
* Contributions are accepted under the
  [Developer Certificate of Origin](https://developercertificate.org/): sign off your
  commits (`git commit -s`).
