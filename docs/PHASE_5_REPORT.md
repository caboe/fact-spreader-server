# Phase 5 report — identity, roles, setup, limits and retention

Date: 2026-11-17. Stack: Docker Compose with a fresh Postgres/Redis/LightRAG volume,
backend and worker built from the Phase 5 tree, stock LightRAG v1.5.0 through the gateway.
Live checks used DeepSeek `deepseek-flash` through the gateway and local Ollama `bge-m3`
for embeddings; no vision model was configured.

## Setup wizard (live, fresh volume)

The volume was removed (`docker compose down -v`), the stack started, and the wizard ran
through the HTTP API only:

| Step | Observed |
| --- | --- |
| `GET /api/setup/status` on the fresh volume | `complete=false`, all six steps false, `next_step=admin` |
| `POST /api/setup/admin` with the deployment token | `201`, pending TOTP secret and `otpauth://` URI returned once |
| `POST /api/setup/admin/totp` | `200`, eight recovery codes |
| login with password + TOTP | `200`, `totp_setup_required=false` |
| `/api/setup/organization` | `200` |
| `/api/setup/provider` (DeepSeek, key tested via `GET /models`) | `200`, 2 models listed |
| `/api/setup/provider` (local Ollama, `use=embedding`) | `200`, `bge-m3:latest` listed |
| `/api/setup/models` | `200`, aliases `fs-chat` … `fs-embedding` |
| `/api/setup/moderation-test` through the gateway | `200`, `backend=llm_classifier:fs-moderation`, `flagged=false` |
| `POST /api/setup/complete` | `200`, instance complete |
| first check (`The Berlin Wall fell in 1989.`) | `202`, job `done`, `insufficient_evidence`, warnings `no_matching_document` |

**Timeline from the backend container start to the first successful check: 28.1 s**
(container started `12:02:41.49Z`, job finished `12:03:09.54Z`). The wizard itself took
2.28 s of HTTP time; the check took 7.33 s from submission to terminal state. The
"under 15 minutes" check is met by a wide margin. Before completion the check endpoint
returned `503 setup_required`; the completion gate requires all six steps, so skipping
provider or moderation testing is refused.

The fresh volume also reset the usage ledger; the spend below preserves the cumulative
figure from before the wipe (`.local/spend-before-phase5-final.txt`).

## Permission matrix

`tests/integration/test_permissions.py` reads the route table from the FastAPI app and
checks every permission-protected route (34 method/path pairs) twice: a key holding the
declared permission must not get `403`, and a credential with no permission must get
`403 permission_denied`. The same file asserts every non-public route rejects an
unauthenticated caller. The matrix the application declares:

| Permission | Routes |
| --- | --- |
| `claims:submit` | `POST /v1/factcheck`, `GET/DELETE /v1/factcheck/{id}`, `GET /v1/factcheck/{id}/events` |
| `claims:recheck` | `POST /v1/claims/{id}/recheck` |
| `search:use` | `POST /v1/search` |
| `documents:submit` | `POST/GET /v1/documents…`, `POST/GET /v1/documents/batches…` |
| `documents:review` | review queue, approve/reject/withdraw, figures, batch approve/reject/retry, editor contradictions and gaps |
| `quality:read` | `DELETE /v1/claims/{id}` |
| `config:manage` | setup organization/provider/models/moderation/complete |
| `users:manage` | `GET/POST/PATCH /v1/users`, password reset |

Additional credential guarantees in the same file:

- an API key cannot hold a permission its owner lacks (it is intersected at creation);
- a user with the roles `editor` and `researcher` gets the union, and an explicit
  `denied_permissions` entry removes a role permission;
- a revoked API key and a revoked device token stop working immediately (`401`);
- a device token defaults to `claims:submit`, cannot call user administration or document
  submission, and requesting `documents:submit` returns `422 permission_escalation`;
- a manager with only `users:manage` cannot create an `editor`.

`tests/integration/test_auth.py` covers TOTP: a privileged session without TOTP is
`403 totp_setup_required` on `/v1/users`, enrolment then allows the call, a plain user
logs in without TOTP and is denied with `permission_denied`, and a `users:manage` password
reset ends the target's existing session (`401`) while the new password logs in.

Live: password-only login for the operator returned `403 totp_required`; a wrong code
returned `401 invalid_totp`.

## Limits and keys

`tests/integration/test_limits.py` lowers `text_chars` on one API key: the key gets
`413 payload_too_large`, a second key of the same user with no tighter limit gets `202`,
and the user's own session gets `202` as well. A user with `requests_per_day=1` gets `202`
on the first check and `429 rate_limit_exceeded` on the second, before a job exists.
`/v1/users` sets and validates limits (`text_chars=0` → `422 invalid_limit`) and reports
`totp_enabled`.

## Retention

Live, after the wizard run:

```
$ docker compose exec backend python -m app.cli retention --dry-run
{'contexts_redacted': 0, 'job_events_deleted': 0, 'jobs_deleted': 0,
 'usage_events_rolled_up': 0, 'usage_events_deleted': 0, 'dry_run': True}
$ docker compose exec backend python -m app.cli retention
… 'dry_run': False
```

The audit log contains one row per run, including the dry run. A regression fixed during
this phase: the dry run used to assign redacted payloads in the session and never commit,
so the audit row disappeared; it now assigns nothing and commits only its audit row.
`tests/integration/test_retention.py` proves the dry run leaves context and job events
untouched while writing the audit row.

The same test seeds two old usage events and one recent one: retention creates one
`usage_rollups` row (2 events, 200/20 tokens, USD 0.002), deletes the two detail events,
keeps the recent event, redacts the old context and deletes the unreferenced terminal job.

## Spend

- At the start of the live run (before the fresh volume): **USD 0.646954**; 71 checks and
  78 result versions.
- After the fresh volume, the wizard and the first check: **USD 0.000707** (one moderation
  and one setup call, both `deepseek-flash`; local embeddings cost nothing).
- Cumulative live spend: **USD 0.647661 of USD 15.00**. The instance budget counter shows
  only the post-wipe amount because the ledger lives in the wiped database.

## Test suite

`make verify` is green: 68 unit tests, 55 integration tests, migration up/down/up plus
drift check, OpenAPI drift, and the compose pin/no-socket/no-host-network check. Regular
tests use Testcontainers and fakes; no test calls a network or a real model.
