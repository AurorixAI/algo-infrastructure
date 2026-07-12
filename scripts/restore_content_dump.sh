#!/usr/bin/env bash
# ALGO — restore a content-service Postgres dump (pg_dump custom format,
# e.g. algo_content_YYYYMMDD_HHMMSS.dump) into the running content-service
# database. Always backs up the CURRENT database first, so restoring an
# older or bad dump is never a one-way trip.
#
# Usage:
#   ./restore_content_dump.sh /path/to/algo_content_20260705_142533.dump
#
# Env overrides (defaults match local dev — see root Makefile):
#   COMPOSE_FILE=docker-compose.staging.yml PROJECT_NAME=algo-staging \
#   CONTAINER=algo-staging-content-db DB_NAME=algo_content \
#     ./restore_content_dump.sh /path/to/dump

set -euo pipefail

DUMP_FILE="${1:?Использование: restore_content_dump.sh <путь-к-dump-файлу>}"
[ -f "$DUMP_FILE" ] || { echo "Файл не найден: $DUMP_FILE"; exit 1; }

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CONTAINER="${CONTAINER:-algo-content-db}"
DB_USER="${DB_USER:-algo}"
DB_NAME="${DB_NAME:-algo_content}"

BACKUP_DIR="$ROOT_DIR/backups"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_pre_restore_$(date +%Y%m%d_%H%M%S).dump"

if ! docker inspect "$CONTAINER" >/dev/null 2>&1; then
  echo "Контейнер '$CONTAINER' не найден или не запущен (docker ps)."
  echo "Для staging: CONTAINER=algo-staging-content-db DB_NAME=algo_content $0 $DUMP_FILE"
  exit 1
fi

echo "1/4  Бэкап текущей $DB_NAME → $BACKUP_FILE"
docker exec "$CONTAINER" pg_dump -U "$DB_USER" -d "$DB_NAME" -F c -f /tmp/algo_restore_backup.dump
docker cp "$CONTAINER:/tmp/algo_restore_backup.dump" "$BACKUP_FILE"
docker exec "$CONTAINER" rm -f /tmp/algo_restore_backup.dump
echo "     готово ($(du -h "$BACKUP_FILE" | cut -f1))"

echo "2/4  Копирую новый дамп в контейнер"
docker cp "$DUMP_FILE" "$CONTAINER:/tmp/algo_restore_incoming.dump"

echo "3/4  Восстанавливаю (--clean — существующие таблицы будут пересозданы из дампа)"
# --if-exists: не падать, если объекта ещё нет (свежий дамп может содержать
#   новые таблицы, которых пока нет в текущей БД).
# --no-owner --no-privileges: не пытаться назначать роли/права из дампа —
#   он мог быть снят в другом окружении с другими именами ролей.
docker exec "$CONTAINER" pg_restore -U "$DB_USER" -d "$DB_NAME" \
  --clean --if-exists --no-owner --no-privileges \
  /tmp/algo_restore_incoming.dump
docker exec "$CONTAINER" rm -f /tmp/algo_restore_incoming.dump

echo "4/4  Строк в таблицах после восстановления:"
docker exec "$CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -c "
SELECT relname AS \"table\", n_live_tup AS rows
FROM pg_stat_user_tables ORDER BY relname;
"

echo
echo "✓ Восстановление завершено."
echo "  Бэкап предыдущего состояния: $BACKUP_FILE"
echo "  Откатить назад:  $0 \"$BACKUP_FILE\""
