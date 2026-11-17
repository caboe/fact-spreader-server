# Phase 8 report — operator admin console (in progress)

Date: 2026-11-17. Phase 8 is in progress. This note records the first slice: the operator
admin console. It is a web UI over the Phase 6 configuration API, not new backend
behaviour.

## What is built

`/admin` is visible in the navigation only when the signed-in session carries
`config:manage` or `users:manage`; the server still decides every request, so hiding the
link is convenience, not security. Pages:

- **Overview** — counts of providers, models, assigned roles, roles needing attention and
  users.
- **Providers and models** — provider table, live connection test, write-only API-key
  replacement (the key is sent once and encrypted; it is never returned), and the model
  table with declared vs tested capabilities and the current role binding.
- **Role assignments** — per gateway role: required capabilities, minimum context,
  current model, the exact rejection reasons from the shared rule, and a model selector
  that calls the validated assignment endpoint.
- **Users** — list with roles, TOTP and active state; create a user with a role; edit roles
  and the four per-user limits; activate/deactivate.
- **Usage** — period filter, totals (calls, tokens, USD), breakdowns by consumer and role,
  daily series and CSV download; quantities only, no contents.
- **Data flow and budgets** — external-data switch, fallback role, per-role monthly USD
  budgets.
- **Re-index** — document count, destructive-action warning, explicit confirmation
  checkbox and a polled job state/progress view.

New typed client calls use the generated OpenAPI types. All copy is translated into
en/de/fr/es.

## Verification

- `svelte-check` 0 errors/warnings; static build succeeds; generated client drift check
  passes (`make web-check`, included in `make verify`).
- Playwright `tests/e2e/admin.spec.ts` runs the console against contract-shaped fixtures,
  so it needs no TOTP credential and spends no model budget: overview counts + axe (no
  serious/critical), providers/models/roles/users/usage rendering, a role assignment
  request, data-flow settings and the re-index confirmation gate. 3 passed.
- Backend endpoints behind the console are covered by the Phase 6 integration tests.

## Open for Phase 8

Editorial queue (approve/reject/withdraw, figures, contradictions, gaps), batch upload,
the remaining settings (personas/methodology/publishers editors), provider/model creation
forms beyond key replacement, plugin handoff and PWA install. The admin console does not
replace those screens.

## Spend

No live model calls were made for this slice; Playwright mocks the config endpoints. The
only spend this session was the earlier browser checks already reported (cumulative USD
0.692702 of USD 15.00 before this slice).
