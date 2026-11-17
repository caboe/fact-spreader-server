# Phase 7 report — web design system and the checking experience

Date: 2026-11-17. Stack: SvelteKit SPA (Svelte 5, Vite 7, Tailwind 4, adapter-static) on
Node 26/pnpm 10, talking to the live Compose backend. No screenshots are mockups: every
image in `docs/screenshots/phase-7/` is a Playwright capture of the running app.

## What is built

- `web/` SvelteKit SPA with `ssr = false`, a static fallback build, Tailwind tokens for
  light/dark via `prefers-color-scheme`, system font stack, reduced-motion handling.
- Generated OpenAPI types (`pnpm gen:api` from `docs/openapi.json`) and a typed client with
  cookie sessions, CSRF on mutations, problem-JSON error mapping and an OpenAI-style error
  reader for chat.
- Runtime i18n catalog for en/de/fr/es covering navigation, forms, verdict labels, job
  states and errors; the language choice is persisted locally. Backend-generated prose is
  displayed as data, never re-translated.
- Screens: **Check** (text, URL, file, image; persona and response-language selection; SSE
  progress and partial statements), **Report** (verdict, warnings, deterministic sections,
  statement verdicts, what is true/missing/unverifiable, evidence provenance, narrative
  only after the consistency check), **Archive** (search, mine filter, versions),
  **Claim** (versions and feedback), **Chat** (checked streaming through the OpenAI
  surface) and **Login**.
- A new backend endpoint `GET /api/auth/session` returns the signed-in user and CSRF token
  after a browser reload; it is CSRF-exempt by being a GET and anonymous callers get 401.

## Verification that ran

- `make web-check` (part of `make verify`): `svelte-check` 0 errors/warnings, static build
  succeeds, generated client is regenerated and drift-checked.
- `make verify` green: 76 unit tests, 66 integration tests, migration up/down/up, OpenAPI
  drift, compose pin/no-socket/no-host-network, plus the web check above.
- Playwright E2E (`web/tests/e2e`, serial against the live stack): the first run had
  **5 passed** (archive search → claim → feedback, chat render, check screen with
  localization/axe/360 px, real text check through SSE in 32.5 s, Markdown file check);
  the final run after the provider key was replaced had **12 passed, 1 skipped**, adding
  the image and URL checks and a streamed chat answer. Screenshots for check/report/
  archive/claim/chat in light, dark, 360 px and 1440 px are in
  `docs/screenshots/phase-7/`.
- Axe (check and chat screens): no serious or critical violations; no horizontal scroll at
  360 px.
- Language switching was exercised live: the check heading changes through de/fr/es.

## Visual revision after the first review

The first human review asked for spacing/density changes, a brand accent that is not the
default link blue, and shadows instead of borders. Applied: the accent is now a deep teal
(`#0f6f64`, dark mode `#5eead4`), cards, evidence, warnings, messages and the checker use
soft layered shadows instead of borders, the header is shorter and sticky with a shadow,
section gaps and the reading measure grew, evidence cards got more internal room, and the
primary button uses an accent-contrast token so the dark-mode mint stays readable. Persona
options are humanised labels. The screenshots in `docs/screenshots/phase-7/` were
regenerated with the new tokens (report screenshots use an existing completed job so the
capture spends no model budget).

## Live E2E after the provider key was replaced

The blocked image run was a provider-account problem, not a pipeline bug: the admin
console showed the stored DeepSeek key answering `402 Insufficient Balance` while its free
`/models` call passed. The human replaced the key in the admin UI; a capability probe of
`fs-moderation` then returned `200`, and the same image check went through on the next
attempt. The vision role stayed on OpenRouter `google/gemini-2.5-flash` (probed).

The full suite then ran against the live stack with the non-TOTP test account
`browser@fact-spreader.local` (the operator account keeps its own TOTP):

**12 passed, 1 skipped** in 4.8 min (`pnpm test:e2e`):

- check screen: accessibility, localization (de/fr/es heading), 360 px overflow;
- real text check through SSE to the report;
- Markdown file check;
- image check (OpenRouter vision for the figure description);
- URL check against `https://example.com/`;
- archive search → claim → version → feedback (with the mine filter cleared so the
  non-owner account sees the corpus);
- chat render and axe;
- admin console: overview, providers/roles/users/usage, settings and the confirmed
  re-index guard (mocked contract fixtures, so no registry mutation);
- design capture: 20 screenshots, light/dark/360/1440.

The one skip is the optional TOTP re-enrolment flow, gated by `FS_E2E_TOTP_SETUP=1` so a
routine run does not touch the operator's authenticator.

A separate chat send was run twice: the first run streamed the checked answer and the
report link but failed the last assertion on a wrong CSS selector; after fixing the
selector the test passes in 48.2 s and shows the streamed answer plus the report link.
No SSE or checked-streaming change was needed.

## Visual acceptance

The human reviewed the revised screenshots and the running app (Check, Report, Archive,
Claim, Chat, admin) and replied on 2026-11-17 that everything is fine from their side. The
`[human]` gate in IMPLEMENT Phase 7 is recorded as accepted; the design revision (teal
accent, shadows instead of borders, more spacing and reading measure, dark-mode contrast,
humanised persona labels) is what was reviewed.

## Spend

Post-fresh-volume ledger: **USD 0.091973** (14 checks, 13 results; probes, setup, LightRAG
and embeddings included). The browser E2E live runs — text, file, image, URL and the chat
send — added USD ~0.042. Cumulative across the project: **USD 0.738927 of USD 15.00**.
