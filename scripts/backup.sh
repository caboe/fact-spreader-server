#!/usr/bin/env bash
# Back up the application database. Uploaded originals live in document_versions.raw_bytes,
# so the dump is the complete authored state; LightRAG is derived and rebuilt from approved
# documents (see docs/OPERATING.md).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DIR="${BACKUP_DIR:-backups}/$STAMP"
mkdir -p "$DIR"

echo "dumping the application database into $DIR/app.dump"
docker compose exec -T postgres sh -ec \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner' > "$DIR/app.dump"

docker compose exec -T postgres sh -ec \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select '\''documents='\'' || count(*) from documents; select '\''users='\'' || count(*) from users;"' \
  > "$DIR/summary.txt"
echo "git=$(git rev-parse HEAD)" >> "$DIR/summary.txt"
echo "created_at=$STAMP" >> "$DIR/summary.txt"
( cd "$DIR" && sha256sum app.dump summary.txt > SHA256SUMS )
echo "backup written: $DIR"
