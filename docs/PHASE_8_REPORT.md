# Phase 8 report — editorial, batch, settings, extension and PWA

Date: 2026-11-17. The Phase 8 agent slices are complete; the `[human]` visual acceptance and
the real-browser plugin test are open. Everything below ran against the live Compose stack
unless it says "contract-mocked".

## What is built

### Operator admin console (first slice)

`/admin` is visible only when the session carries `config:manage` or `users:manage`; the
server still decides every request. Overview, providers and models with connection test
and write-only key replacement, role assignments with the shared rejection reasons, user
administration and limits, usage summaries/CSV (quantities only), data-flow and role
budgets, and the confirmed re-index view. All copy is translated into en/de/fr/es.

### Editorial queue

`/editorial` has three tabs. The queue lists ready/warning/duplicate documents with state
counts and a state filter (pending, approved, indexed, rejected, withdrawn), a detail pane
with the document text, warnings, figure descriptions that can be corrected and saved, and
approval/rejection/withdrawal. Approval requires the licence confirmation and a
redistribution choice; a preselected batch can be approved in one pass. The contradictions
tab acknowledges or resolves editor findings; the gaps tab links or dismisses gaps and
re-checks sample results within the daily re-check budget. A live run approved a queued
warning document, waited until the worker indexed it and then withdrew it, so the corpus
ended unchanged.

### Batch upload

`POST /v1/documents/batches/estimate` is a new multipart endpoint that applies the same ZIP
sanitisation and size/count limits as submission, returns the estimated USD cost, the
remaining monthly budget and the file list, and creates no rows and no model call. The UI
(`/submit`) accepts drag-and-drop, a file picker, a folder, a ZIP, a URL list, batch
metadata and a CSV/JSON sidecar; it shows the estimate and blocks submission above the
budget until the overspend is confirmed. After submission it polls per-file states, shows
summary counts, retries failed files, and approves or rejects selected files. The batch id
is kept in local storage, so closing and reopening the window resumes the same batch. The
live run submitted a Markdown file and a PNG, saw the PNG fail with a per-file reason,
retried it, approved the Markdown file and then withdrew the indexed document.

A retry of a stored image used to escape as a `500` because `UrlFetchError` was not caught
in `retry_failed_document`; it now returns a per-file `parse_warning`. A regression test
covers that path.

### Curation settings

`/admin/curation` edits publisher grade/dispute overrides with the local-vs-shipped diff,
persona tone/max-words/enabled for base and custom personas (custom ones can be deleted),
checklist staleness and pattern definition/mechanism, and shows the instance language
lists. The moderation test console runs the wizard's benign probe and reports pass/fail;
the endpoint now requires `{"confirm": true}` because it spends a model call, and a live
probe returned `llm_classifier:fs-moderation`, `flagged: false`.

### First-run setup wizard

`/setup` is a step-per-screen wizard: administrator + setup token, TOTP secret and
confirmation, recovery codes, organization and budget, provider connection test with the
returned model list, chat/embedding model assignment, moderation test and completion. It
resumes from `/api/setup/status` after a reload. The screens are contract-mocked in the E2E
suite; the zero-volume backend flow was proven live in Phase 5 (28.1 s to the first check)
and is not repeated here because it would destroy the working instance. This is recorded
as a deliberate gap, not as a passed live check.

### Extension connection

`/connect` creates a device token (shown once, copyable), lists devices and revokes them.
When the page was opened as an extension popup with `?state=…`, it posts the token to the
extension origin via `window.opener.postMessage` only if the referrer is a
`chrome-extension://` or `moz-extension://` origin. `docs/EXTENSION.md` documents the token,
the one-time handoff, the compact check flow, CORS (`CORS_EXTENSION_ORIGINS`), image sizing
and the boundary rules. A live run created a token, submitted a compact check with it
over `POST /v1/factcheck`, received `result.compact` with a verdict, revoked the device and
got `401` from the next request.

### PWA

The web manifest has 192/512 PNG icons, a maskable icon, an apple-touch icon and a share
target (`/?text=…&url=…`); the check page prefills shared text or URL. A service worker
caches the app shell and static assets, never `/api` or `/v1`, and falls back to the cached
shell for offline navigations. The shell registers it only in production builds and shows
an install button when the browser offers one, or the iOS Share → Add to Home Screen hint.
A production build was produced; installing on a physical device is part of the human gate.

## Verification

- `make verify` green after the changes: format/lint/typecheck, 77 unit tests, 66+
  integration tests including the permission matrix over the new routes, migration
  up/down/up, OpenAPI drift, compose guard and the web check.
- Playwright against the live stack: **27 passed, 2 skipped** (`pnpm test:e2e`, 5.1 min).
  The skips are the optional TOTP re-enrolment and the editorial live approval, which
  needs a queued document; that flow was run separately and green (approve → indexed →
  withdraw). The suite includes mocked admin, editorial, batch, curation, connect and setup
  screens with axe (no serious/critical violations) and light/dark/360/1440 captures, plus
  live text/file/image/URL checks, a streamed chat answer, the live batch cycle, the live
  device-token compact check, archive feedback and the localization/accessibility checks.
- Screenshots are in `docs/screenshots/phase-8/`: editorial, submit, admin overview,
  providers, roles, users, usage, settings, reindex, curation, connect and setup, each in
  light/dark/narrow/wide.

## Deliberately not built

These items from the Phase 8 scope need backend surface that does not exist yet; they are
honest follow-ups, not hidden gaps:

- API-key management in the web UI (`/api/api-keys` per PROTOCOL §11.3; keys are still
  created with `make cli`/`app.cli create-api-key`).
- Retention status, the four-eyes toggle and backup status as settings screens; retention
  is a CLI job, four-eyes is an environment flag and backups are Phase 9 operations.
- Persona test console (the persona editors exist; running a sample check per persona is a
  paid evaluation and belongs to Phase 9).
- The setup wizard has not been driven through a real zero-volume instance in a browser;
  see above.

## Spend

Post-fresh-volume ledger: **USD 0.149079** (22 checks, 21 results; probes, setup, LightRAG,
embeddings and the live E2E calls included). Cumulative across the project:
**USD 0.796033 of USD 15.00**.

## Human gate

Visual acceptance was given on 2026-11-17: the human reviewed the editorial, batch, usage,
settings, curation, connect and setup screens and the PWA install and said everything looks
okay. The real-browser plugin test is deferred by the human because the extension is built
later; it is not recorded as passed. The zero-volume browser run of the setup wizard also
moves to the Phase 9 clean-start acceptance, which starts a fresh stack anyway.

Open follow-ups (not gates): API-key management UI, retention/four-eyes/backup screens and
the persona test console, all waiting for their backend surface; the Docling layout/OCR
item from Phase 4.
