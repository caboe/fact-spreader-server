# Phase 4 report — document pipeline and editorial workflow

Date: 2026-11-17. Stack: Docker Compose, backend/worker from the Phase 4 tree, stock
LightRAG v1.5.0 through the gateway, Postgres with pgvector + AGE, Redis. Live model calls
used DeepSeek through the gateway, local Ollama `bge-m3` and the OpenRouter vision model.
Spend at the end of the phase: **USD 0.646954** of USD 15.00; 71 checks and 78 stored
result versions.

## Document lifecycle (live)

A Destatis housing report was submitted as Markdown, reviewed and approved through the
API, queued for `document_index`, and indexed by the worker in **10.1 s**
(`doc_01M7MK6AEGXVYYAW79YYKJK765`). A check for “Rents rose by 4 percent in 2025.” cited
it as `E1`; the verdict was `insufficient_evidence` because the audit stayed open, not
because the source was missing. A resubmission of the same bytes returned state
`duplicate` with `duplicate_of`. Withdrawal removes the `doc@v` file source and marks the
document withdrawn; past results render that evidence with `provenance.withdrawn = true`
at read time, without mutating the stored row.

## PDF figures, tables and scans

- An image-only PDF (no text layer) was submitted through the API and returned in **1.8 s**
  with `state = ready`, one figure on page 1, `description_model_id = fs-vision`, a correct
  description and `estimate = {pages: 1, figures: 1, vision_calls: 1, estimated_usd: 0.0031}`.
- Embedded PDF images are extracted with pypdf, sanitised with Pillow and described by
  `fs-vision`; the description is appended to the Markdown body.
- HTML tables are converted to GitHub Markdown by the shared reader. Live content:
  `| Year | Rate |` / `| --- | --- |` / `| 2025 | 6 percent |`. Submitted PDFs append up
  to ten pdfplumber tables across twenty pages.
- Docling is not installed. The behavioural acceptance (tables as Markdown, scanned page,
  stored figure with page/model) is met by pdfplumber/pypdf plus vision. Docling layout
  reconstruction and OCR layout remain a non-blocking follow-up before Phase 9
  evaluation; this is recorded rather than presented as done.

## Batches

- Live batch with one Markdown file and a ZIP containing two identical entries, a `../`
  path and a symlink: counts `total 3, ready 1, duplicate 2, failed 0`, two
  `zip_sanitized` warnings, unsafe entries skipped; `GET` returned the same counts.
- A CSV metadata sidecar set title, license and domain tags per file. Live:
  title `Sidecar live title`, license `CC0-1.0`, tags `["transport"]`.
- A batch test covers every warning class required by the acceptance: duplicate,
  unsupported language, injection, low source grade and missing license, plus the
  preselection rule for clean documents.
- Failed entries retain their raw bytes and can be retried individually; the retry
  reparses, recomputes warnings and moves the document to ready/warning.
- Cost estimate: an image-only PDF batch estimated **0.00033 USD** and consumed
  **0.00029 USD** (13.8% difference). A batch whose estimate exceeds the remaining budget
  is refused with `429 budget_exceeded` before any parse unless `accept_estimate` is set.

## Review rules

Approval of one's own document is allowed with four-eyes off and returns
`403 four_eyes_required` with it on. Rejection keeps the document out of LightRAG.
Approval queues indexing and then bounded re-checks for matching claims; over-budget
claims surface as a `budget_low` warning with the skipped count. The daily counter is
shared with gap re-checks. Figure descriptions can be corrected by a reviewer and are
then marked `editor_checked`.

## Automated checks

`make verify` is green: **67 unit tests, 39 integration tests**, formatting, lint, strict
mypy, Alembic up/down/up and drift, OpenAPI drift and the compose policy check. The new
tests cover document lifecycle, PDF figures, batch warning classes, ZIP sanitisation,
metadata sidecars, retry, estimates/budget blocking, four-eyes, rechecks, archive version
chains and gap re-checks.

## Open follow-ups

- Docling layout/OCR for hard scans and complex table layouts; the current path covers
  digital tables, image-only PDFs and figures.
- A formal per-file withdrawn marker in stored historical reports is rendered at read
  time, not persisted.
- Batch approval/rejection results are returned per file but do not yet emit individual
  audit events for every approved document.
