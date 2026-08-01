#!/usr/bin/env bash
# Restores a dump produced by backup.sh.
#
# This is destructive, so it refuses to run unless the caller both names the
# dump and confirms explicitly. A restore that "just works" from a stray
# argument is how a production database gets overwritten during a drill.
set -euo pipefail

usage() {
  cat <<'EOF'
用法: restore.sh <dump 文件> --confirm

环境变量:
  DATABASE_URL   目标库，默认 postgresql://zaolang:zaolang@localhost:5433/zaolang
  RESTORE_JOBS   并行度，默认 4
EOF
}

DUMP_FILE="${1:-}"
CONFIRM="${2:-}"

if [[ -z "$DUMP_FILE" || "$DUMP_FILE" == "-h" || "$DUMP_FILE" == "--help" ]]; then
  usage
  exit 1
fi

if [[ ! -f "$DUMP_FILE" ]]; then
  echo "找不到备份文件: $DUMP_FILE" >&2
  exit 1
fi

if [[ "$CONFIRM" != "--confirm" ]]; then
  echo "恢复会覆盖目标库的全部数据。确认后请追加 --confirm。" >&2
  exit 1
fi

DB_URL="${DATABASE_URL:-postgresql://zaolang:zaolang@localhost:5433/zaolang}"
DB_URL="${DB_URL/postgresql+psycopg:\/\//postgresql://}"

if [[ "$DB_URL" == *"prod"* ]]; then
  echo "目标看起来是生产库，脚本拒绝执行。" >&2
  exit 1
fi

echo "==> restoring $DUMP_FILE"
# --clean drops objects first; without --if-exists a fresh database would fail
# on the first missing object instead of restoring.
pg_restore \
  --dbname "$DB_URL" \
  --clean --if-exists --no-owner --no-privileges \
  --jobs "${RESTORE_JOBS:-4}" \
  "$DUMP_FILE"

echo "==> verifying alembic revision"
psql "$DB_URL" -tAc 'SELECT version_num FROM alembic_version' || {
  echo "恢复完成，但没有找到 alembic_version，请确认备份是否完整。" >&2
  exit 1
}

echo "==> done"
