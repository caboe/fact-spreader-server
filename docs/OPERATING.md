# Operating Fact Spreader

## Requirements

Docker with Compose v2, a browser, and an approved provider key. The default stack is
Postgres + pgvector/AGE, Redis, the FastAPI backend, one or more workers, stock LightRAG
v1.5.0 and a Caddy edge that serves the static SPA. The local stack binds only to loopback.

## First start

```bash
cp .env.example .env       # fill secrets; never commit this file
make install               # uv sync --frozen and pnpm install --frozen-lockfile
make stack-up              # build and start everything
```

Open <https://localhost:8443> (Caddy internal CA: accept the certificate warning in
development). With a fresh volume, complete the wizard: setup token from `.env`, admin
account, TOTP, organization and budget, provider test, chat/embedding models, moderation
test. The wizard is the supported path; `make bootstrap` remains the CI/automation path and
creates the instance, admin, providers/models and a smoke API key without the wizard.

Then submit a first document (`/submit`), approve it in `/editorial`, wait for indexing and
run a check on `/`. The check must cite only approved documents.

## Health and logs

```bash
make stack-logs
curl -k https://localhost:8443/healthz
curl -k https://localhost:8443/readyz
docker compose ps
```

Caddy does not write access logs by default. Backend logs are structured JSON with request
ids and contain no claim text, prompts or provider secrets. `/metrics` is not exposed; the
edge returns `404`, and `/internal/*` is never proxied.

## HTTPS

The bundled Caddyfile uses `tls internal` for developer machines. For a real deployment,
change the site address in `deploy/caddy/Caddyfile` to the public hostname and remove the
`tls internal` line; Caddy obtains a Let's Encrypt certificate automatically. Keep the
`/internal` and `/metrics` blocks. The SPA, `/api`, `/v1` and server-sent events are all
served by the same edge; do not expose the backend port publicly.

## Backup and restore

Uploaded originals and approved text live in the application database
(`document_versions.raw_bytes`); LightRAG is derived and can be rebuilt from approved
documents.

```bash
make backup                    # backups/<timestamp>/app.dump + summary + SHA256SUMS
make backup-test [BACKUP]      # restores into a disposable project, reindexes, runs a check
```

`backup-test` uses a separate Compose project (`fs-backup-test-*`), alternate ports and
throwaway volumes, restores the dump, starts the stack, rebuilds the corpus from approved
documents and runs one real check. It never touches the running project. Keep
`backups/` off the repository (it is git-ignored) and copy it to durable storage.

## Re-index

Changing an embedding, extraction, vision or figure-description model is an explicit,
confirmed re-index (`/admin/reindex` or `POST /v1/config/reindex`). The worker rebuilds
LightRAG from approved documents. Re-index after a restore if the LightRAG volume was not
backed up. During a re-index, checks keep reading the current corpus.

## Retrieval

`/retrieval` shows exactly what stock LightRAG returns and applies no relevance cut, so on a
small corpus it returns almost everything. Two settings decide what the index can see.

`hnsw.ef_search = 200` is set on the `lightrag` database at init. pgvector's default of 40
let the HNSW scan reach only part of the index (measured: 17 of 28 chunks), so a relevant
passage could be missing from checks. A volume created before this setting needs it once,
followed by a LightRAG restart so the connection pool opens fresh sessions:

```bash
docker compose exec -T postgres psql -U factspreader -d lightrag \
  -c "LOAD 'vector';" -c "ALTER DATABASE lightrag SET hnsw.ef_search = 200;"
docker compose restart lightrag
```

Use `POSTGRES_USER` and `LIGHTRAG_DB_NAME` from `.env` if you changed them. `LOAD 'vector'`
is required in that session: without the extension loaded, PostgreSQL does not know the
parameter and rejects the `ALTER`.

## Retention and budgets

```bash
make retention            # redact old contexts, roll usage into monthly aggregates
make spend                # month-to-date spend and remaining instance budget
```

Retention is a scheduled operator job; it does not delete results, only old contexts and
job events. Budgets are enforced before every model call; an exhausted budget fails closed.

## Upgrade

1. Back up first (`make backup`).
2. Pull the new tree and images (pinned in `docker-compose.yml` and `backend/uv.lock`).
3. `make verify` on the new tree.
4. `make stack-up`; migrations run in the backend entrypoint.
5. Run `make backup-test` against the backup, then a check and the eval set.

The database schema is migrated forward by Alembic; there is no automatic downgrade. To go
back, restore the backup into a fresh volume.

## Clean start

```bash
make stack-down
docker compose down -v        # deletes volumes; asks nothing, be sure
make stack-up
```

Then use the wizard. A clean start is the acceptance path in `docs/PHASE_9_REPORT.md`.
