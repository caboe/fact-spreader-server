# Security

This document describes the threat model, the controls this stack implements and how to
check them. It does not claim completeness; the limitations are listed at the end.

## Threats and controls

| Threat | Control | Evidence |
| --- | --- | --- |
| Prompt injection in a claim, document, URL, figure description or plugin text | Untrusted text is wrapped as data in every prompt; extraction and verification use schema-validated output; retrieved text is never executed as instructions; document warnings flag suspected injection | `test_upload_security`, document ingestion tests, `tests/fixtures/corpus/crime-injection-document.md`, `claim-028`/`claim-048` |
| A model invents evidence IDs or verdicts | Verdicts and evidence links come from strict structured output and are checked against the retrieved evidence set; the overall verdict, gate and contradictions are pure code | verification tests, `backend/app/pipeline/verification.py`, `app/services/gate.py` |
| SSRF through a submitted URL | Only public IPs, every redirect target is re-validated, DNS answers are all checked | `test_ssrf`, `docs/EVALUATION.md` security cases |
| ZIP traversal, symlinks, bombs and oversized uploads | ZIP entries are sanitised before parsing; absolute/traversal/symlink/oversized entries are skipped and reported; per-file and total limits | `test_upload_security` |
| File type confusion | Image signatures are checked before decoding and win over the extension; a PDF magic header is parsed as PDF | `test_upload_security` |
| Secret leakage | API keys and device tokens are stored hashed and shown once; provider keys are encrypted with `APP_SECRET_KEY`; secrets are never logged; Caddy strips `/internal` and `/metrics` | key/secret tests, response tests, Caddyfile |
| Privilege escalation | Permissions are enforced server-side on every protected route; API keys and device tokens can never exceed their owner; TOTP is required for privileged permissions | permission matrix, `test_permissions.py`, TOTP tests |
| CSRF and session fixation | Session cookie is HttpOnly and SameSite=Lax; state-changing `/api` requests need the CSRF token; login rotates to a fresh session; TOTP is checked on privileged login | auth tests, `X-CSRF-Token` in the client |
| Moderation evasion or classifier failure | Check inputs are flagged, not blocked, except `sexual_minors` which has a deterministic floor and is never configurable; an unavailable or unparseable classifier fails closed | moderation tests, `claim` moderation set |
| Provider or network outage | Every outbound call has a timeout, retries and a circuit breaker; a failed moderation or retrieval fails closed instead of returning an unchecked answer | transport tests, fail-closed tests |
| Resource exhaustion | Request, text, file, batch and budget limits are enforced before expensive work; role and monthly budgets stop calls | limits tests, usage tests |
| Data exfiltration through usage views | Usage shows counts and costs only, never claim text; identity is visible only to the roles named in the notes | usage tests, UI review |
| Container breakout | No Docker socket, no host network, no privileged container; application containers run as non-root | `make compose-check` |

## Running the security checks

```bash
make verify                                  # unit + integration, includes the permission matrix
make test-integration                        # Testcontainers, no network
cd backend && uv run pytest tests/unit/test_ssrf.py tests/unit/test_upload_security.py -q
make schemathesis                            # live /v1 schema fuzzing (no state-changing methods)
```

`make schemathesis` uses the eval API key file and exercises read-only `/v1` operations.
It fails on a 5xx or an undocumented status code. It is not part of `make verify` because it
needs the live stack.

## Deliberate limitations

- A local instance serves the edge with Caddy's internal CA. A production deployment must
  replace `tls internal` with a real certificate (automatic HTTPS) and set the site address.
- The evaluation sets are small and synthetic; they are a regression measure, not a
  safety certification.
- Moderator output is probabilistic. Only the `sexual_minors` floor is deterministic.
- The stack trusts its own network for Postgres/Redis/LightRAG; those ports are bound to
  loopback and never exposed by Caddy.
- Dependency audit (`pip-audit`, `pnpm audit`) is not wired into CI yet; the lockfiles are
  committed so an audit can be run offline.
