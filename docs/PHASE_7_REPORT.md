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
- Playwright E2E (`web/tests/e2e`, serial against the live stack): **5 passed** —
  archive search → claim → feedback, chat screen render, check screen (localization,
  axe, 360 px overflow), real text check from input through SSE to the report (32.5 s
  including the model), and a Markdown file check. Screenshots for check/report/archive/
  claim/chat in light, dark, 360 px and 1440 px were written to
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

## Blocked: the live provider balance

The image E2E test failed with `provider_rejected: Insufficient Balance` from DeepSeek, and
the URL test did not run because it is ordered after it. After the human reported a
top-up, a direct capability probe and a browser check still returned
`provider_error:402:Insufficient Balance` (request ids `085c4d94…` and the preceding
`f64e4609…`), so the account still has no usable credit from this deployment's key. The
failure is the provider balance, not the UI or the pipeline: the job was created, reached
the worker and stopped at the first paid call. No further live check can run until the
account really has credit or the human approves moving chat/moderation to another
provider.

Consequences for the Phase 7 done-when list:

- text and file checks are proven end to end in the browser;
- image and URL checks are implemented and wired, but their live E2E run is not green;
- chat sends through the checked-streaming endpoint, but a costly E2E send was not run
  before the balance ran out.

## Gaps to close before the human gate can pass

1. Confirm the DeepSeek key/account that the stack actually uses (the wizard stored the
   key from `.env`); the current key still answers 402 after the reported top-up. Then re-run
   `make web-e2e`; the image test uses the probed OpenRouter vision model (role
   `fs-vision`) and the URL test uses `https://example.com/`.
2. Capture the chat answer (one send) after that run.
3. Human visual acceptance of the revised screenshots against PURPOSE §3.14. The agent
   stops here.

## Spend

Post-fresh-volume ledger: USD 0.045748 (7 checks, 6 results) of which the browser runs are
USD ~0.04. Cumulative across the project: **USD 0.692702 of USD 15.00**.
