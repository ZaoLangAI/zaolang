#!/usr/bin/env bash
# Dumps the database to a local file and, when MinIO credentials are present,
# uploads it alongside the backups the admin console creates.
#
# Custom format is used rather than plain SQL so restore can run in parallel and
# select individual tables during an incident.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${BACKUP_DIR:-$ROOT/.backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="$OUT_DIR/zaolang-$STAMP.dump"

DB_URL="${DATABASE_URL:-postgresql://zaolang:zaolang@localhost:5433/zaolang}"
# The app speaks SQLAlchemy's dialect prefix; pg_dump does not.
DB_URL="${DB_URL/postgresql+psycopg:\/\//postgresql://}"

mkdir -p "$OUT_DIR"

echo "==> dumping to $OUT_FILE"
pg_dump --format=custom --no-owner --no-privileges --file "$OUT_FILE" "$DB_URL"

SIZE="$(wc -c <"$OUT_FILE" | tr -d ' ')"
echo "==> wrote $SIZE bytes"

if command -v mc >/dev/null 2>&1 && [[ -n "${S3_BUCKET:-}" ]]; then
  echo "==> uploading to s3://${S3_BUCKET}/backups/db/"
  mc cp "$OUT_FILE" "local/${S3_BUCKET}/backups/db/"
else
  echo "==> skipping upload (mc or S3_BUCKET not configured)"
fi

# Local copies are a disk-space risk on a dev machine, so only the last few stay.
KEEP="${BACKUP_KEEP:-5}"
ls -1t "$OUT_DIR"/zaolang-*.dump 2>/dev/null | tail -n "+$((KEEP + 1))" | while read -r old; do
  echo "==> pruning $old"
  rm -f "$old"
done

echo "$OUT_FILE"
