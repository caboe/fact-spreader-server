#!/usr/bin/env bash
# Restore a backup into a throwaway compose project, rebuild the derived LightRAG corpus
# and run one real check. Never touches the running stack's project or volumes.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BACKUP="${1:-}"
if [[ -z "$BACKUP" ]]; then
  BACKUP="$(find backups -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -1)"
fi
if [[ -z "$BACKUP" || ! -f "$BACKUP/app.dump" ]]; then
  echo "no backup found; run make backup first" >&2
  exit 2
fi
BACKUP="$(cd "$BACKUP" && pwd)"
PROJECT="fs-backup-test-$$"
OVERRIDE=".local/backup-test.compose.yml"
mkdir -p .local
cat > "$OVERRIDE" <<'YAML'
services:
  postgres:
    ports: !override ["127.0.0.1:15432:5432"]
  redis:
    ports: !override ["127.0.0.1:16379:6379"]
  backend:
    ports: !override ["127.0.0.1:18000:8000"]
  lightrag:
    ports: !override ["127.0.0.1:19621:9621"]
  caddy:
    ports: !override ["127.0.0.1:18443:443"]
YAML
COMPOSE=(docker compose -p "$PROJECT" -f docker-compose.yml -f "$OVERRIDE")
cleanup() { "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo "starting a fresh postgres for $PROJECT"
"${COMPOSE[@]}" up -d postgres redis --no-build

echo "waiting for postgres"
for _ in $(seq 1 60); do
  if "${COMPOSE[@]}" exec -T postgres pg_isready -U factspreader -d app >/dev/null 2>&1; then break; fi
  sleep 1
done

echo "restoring $BACKUP/app.dump"
"${COMPOSE[@]}" exec -T postgres sh -ec \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists' \
  < "$BACKUP/app.dump"

echo "starting backend, worker and LightRAG"
"${COMPOSE[@]}" up -d backend worker lightrag --no-build
for _ in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:18000/healthz >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:18000/healthz >/dev/null
for _ in $(seq 1 120); do
  if curl -fsS http://127.0.0.1:19621/health >/dev/null 2>&1; then break; fi
  sleep 1
done

EMAIL="$("${COMPOSE[@]}" exec -T postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select email from users order by created_at limit 1"')"
KEY="$("${COMPOSE[@]}" exec -T backend python -m app.cli create-api-key --email "$EMAIL" --name backup-test | tail -1)"
AUTH=(-H "Authorization: Bearer $KEY")

echo "rebuilding the derived corpus from approved documents"
REINDEX="$(curl -fsS -X POST http://127.0.0.1:18000/v1/config/reindex \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $KEY" \
  -d '{"confirm": true, "reason": "backup-test"}')"
JOB="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])' <<<"$REINDEX")"
for _ in $(seq 1 180); do
  STATE="$(curl -fsS -H "Authorization: Bearer $KEY" "http://127.0.0.1:18000/v1/config/reindex/$JOB" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
  if [[ "$STATE" == "done" ]]; then break; fi
  if [[ "$STATE" == "failed" ]]; then echo "reindex failed" >&2; exit 1; fi
  sleep 2
done
[[ "$STATE" == "done" ]] || { echo "reindex did not finish" >&2; exit 1; }

echo "running one check against the restored stack"
CHECK="$(curl -fsS -X POST http://127.0.0.1:18000/v1/factcheck \
  -H 'Content-Type: application/json' -H "Authorization: Bearer $KEY" \
  -d '{"input":{"type":"text","text":"Registered crime by non-German suspects has risen sharply since 2015."},"fast":true}')"
CHECK_JOB="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["job"]["id"])' <<<"$CHECK")"
for _ in $(seq 1 180); do
  RESULT="$(curl -fsS -H "Authorization: Bearer $KEY" "http://127.0.0.1:18000/v1/factcheck/$CHECK_JOB")"
  if python3 -c 'import json,sys; d=json.load(sys.stdin); r=d.get("result"); sys.exit(0 if r and r.get("result",{}).get("overall_verdict") else 1)' <<<"$RESULT"; then
    VERDICT="$(python3 -c 'import json,sys; print(json.load(sys.stdin)["result"]["result"]["overall_verdict"])' <<<"$RESULT")"
    break
  fi
  sleep 2
done
[[ -n "${VERDICT:-}" ]] || { echo "restored check produced no verdict" >&2; exit 1; }
echo "backup-test passed: restored $(basename "$BACKUP"), reindexed, check verdict=$VERDICT"
