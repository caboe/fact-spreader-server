# Source Quality Grading

PURPOSE §3.1b defines how evidence is graded. This document is the operator-facing
version of that policy and of the shipped list in
[`methodology/publishers.json`](../methodology/publishers.json).

## What a grade means

The grade describes the **original publisher** of a source. It is independent of
the **evidence tier**, which describes the retrieval channel (local corpus, live
peer, validated web, parametric knowledge).

| Grade | Typical sources |
| --- | --- |
| `A` | Official statistics, peer-reviewed research, systematic reviews and meta-analyses |
| `B` | Established research institutes, intergovernmental organizations, NGOs with transparent methodology |
| `C` | Quality journalism, grey literature |
| `D` | Advocacy material, unknown or unassessed sources |

The operator sets the minimum grade that counts toward the minimum-source gate;
the default is `B`.

## The five criteria

Every entry's `basis` is a short statement of which of these criteria it meets:

1. **Methodological transparency** — does the source say how the number was
   produced, and can a reader check it?
2. **Quality assurance** — peer review, or a documented equivalent (multi-stage
   expert review, an editorial process with named responsibility).
3. **Corrections policy** — does the publisher correct and label errors?
4. **Institutional independence** — is the publisher structurally independent of
   whoever benefits from the conclusion?
5. **Disclosure of funding and conflicts of interest** — are they stated?

Grades reflect these criteria and **never** the political orientation of a source
or the conclusions it reaches. Advocacy organizations of every orientation are
graded by the same rules and normally land at `D`.

## Rules the implementation enforces

* **Resolution order:** per-document override → local list → shipped list → `D`.
* **Ordering matters.** The first matching entry wins, so narrow entries (a
  domain, a DOI prefix) are listed before broad ones (a name pattern).
* **Matching** is by DOI prefix, by domain (host or subdomain) or by publisher
  name/alias pattern. Aliases include the German names of German institutions,
  because the corpus is English **and** German (PURPOSE §3.11).
* **Disputed entries** (`"disputed": true`) have an effective grade of at most
  `C` until the dispute is resolved.
* **Peer-declared grades** are capped by the trust cap of the peer they arrived
  from, and the basis records both the declared grade and the cap.
* **The effective basis is stored** with every evidence item and every
  `FactCheckResult`. A later list change (a new release, or a local override)
  therefore never silently changes a past verdict. `POST /api/publishers/impact`
  lists the cached results a change would affect, and `PUT /api/publishers/{key}`
  records the override without touching them.
* **A local override is a separate row** (`<key>__local`, with `overrides_key`
  pointing at the shipped entry), so the shipped baseline stays intact and
  `GET /api/publishers/diff` can always show what the operator changed.
* **Granularity.** An entry can grade a whole publisher or one product of it
  (for example a peer-reviewed journal series versus the same institute's blog).
  The current shipped list does not yet exercise the per-product case.

## Editing the list

* **Locally:** add, override or disable any entry through `/api/publishers` (or
  the dashboard). The diff against the shipped list is always visible
  ("overridden locally"); overriding a shipped key writes a `<key>__local` row
  that suppresses the shipped entry during resolution.
* **Try before you save:** `POST /api/publishers/resolve` shows which entry would
  match a URL, DOI, publisher or title, and on what it matched.
* **Upstream:** changes to `publishers.json` go through a review with a written
  rationale (`reviewed_by`, `reviewed_at`). A release upgrade updates the shipped
  entries, keeps local overrides, and lists the conflicts.
* **Exchanging lists between instances** is explicitly a v2 candidate
  (PURPOSE §6) and is not implemented.

## Editorial decisions

The grade is part of the approval decision, not a silent default:

* **Approval requires a grade.** The approval form starts with an empty `A`/`B`/`C`/`D`
  choice and the API rejects a missing `source_quality`. The computed grade (often `D` for
  a publisher with no list entry) is shown as a suggestion with its basis, but the editor
  must select the grade deliberately.
* **Later changes are explicit.** A reviewer can change the grade of an approved or indexed
  document, or a filtered selection of them, from the editorial list. Every change is
  audited with the previous grade. It does not re-index the document and, by explicit
  product decision, does not enqueue re-checks; stored results keep their original basis.
  A new check after the change uses the new grade.
* **Bulk changes do not bypass review.** Select-all in the editorial list applies to the
  current filter; the API accepts at most 200 ids and returns a per-document result.

## What the grade is not

A high grade is not a guarantee about a specific number. Statistics get revised,
studies have limitations, and a grade `A` publisher can still publish a weak
report. The grade answers "how much process stands behind this publisher", not
"is this particular sentence true". The pipeline's job is to check the sentence;
the grade only decides whether the source may count toward the gate.

## Categories with no entry

Anything not matched grades `D` and therefore normally cannot satisfy the gate on
its own. That is intentional: an unassessed source is not a weak source, it is an
unassessed one. If it matters, add an entry with a written basis.
