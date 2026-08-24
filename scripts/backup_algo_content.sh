#!/usr/bin/env bash
# ==============================================================================
# ALGO — lossless backup of algo_content (tasks DB only)
#
# Usage:
#   ./backup_algo_content.sh [output_dir]
#
# Creates:
#   algo_content_<timestamp>.dump      — pg_dump custom format (schema+data+blobs)
#   algo_content_<timestamp>.manifest.json
#   algo_content_<timestamp>.sha256
#
# Verify-only (existing dump):
#   VERIFY_ONLY=1 DUMP_FILE=path/to.dump ./backup_algo_content.sh
# ==============================================================================
set -euo pipefail

CONTAINER="${CONTENT_PG_CONTAINER:-content-postgres}"
DB_USER="${POSTGRES_USER:-algo}"
DB_NAME="${POSTGRES_DB:-algo_content}"
DB_PASS="${POSTGRES_PASSWORD:-algo_password}"
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
OUT_DIR="${1:-$(cd "$(dirname "$0")/../.." && pwd)/backups/algo_content}"
VERIFY_DB="algo_content_verify_${TIMESTAMP}"

log() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*"; }

count_rows() {
  docker exec -e PGPASSWORD="$DB_PASS" "$CONTAINER" \
    psql -U "$DB_USER" -d "$1" -At -c "
      SELECT json_build_object(
        'tasks_master',        (SELECT count(*) FROM tasks_master),
        'textbook_tasks',      (SELECT count(*) FROM textbook_tasks),
        'task_figure_refs',    (SELECT count(*) FROM task_figure_refs),
        'textbook_toc',        (SELECT count(*) FROM textbook_toc),
        'task_figures',        (SELECT count(*) FROM task_figures),
        'textbooks',           (SELECT count(*) FROM textbooks),
        'g8_tasks',            (SELECT count(*) FROM tasks_master WHERE id LIKE 'G8_%'),
        'g8_verified',         (SELECT count(*) FROM tasks_master WHERE id LIKE 'G8_%' AND verification_status='verified'),
        'g8_with_dist',        (SELECT count(*) FROM tasks_master WHERE id LIKE 'G8_%' AND jsonb_array_length(COALESCE(distractor_meta,'[]'::jsonb)) >= 2)
      )::text;
    "
}

if [[ "${VERIFY_ONLY:-0}" == "1" ]]; then
  DUMP_FILE="${DUMP_FILE:?DUMP_FILE required}"
  log "Verify-only mode: $DUMP_FILE"
  OUT_DIR=$(dirname "$DUMP_FILE")
  TIMESTAMP=$(basename "$DUMP_FILE" | sed -E 's/algo_content_([0-9_]+)\.dump/\1/')
else
  mkdir -p "$OUT_DIR"
  DUMP_FILE="${OUT_DIR}/algo_content_${TIMESTAMP}.dump"
  MANIFEST="${OUT_DIR}/algo_content_${TIMESTAMP}.manifest.json"
  CHECKSUM="${OUT_DIR}/algo_content_${TIMESTAMP}.sha256"

  log "=== Backup algo_content → $DUMP_FILE ==="

  if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    log "ERROR: container $CONTAINER not running"
    exit 1
  fi

  SRC_COUNTS=$(count_rows "$DB_NAME")
  log "Source row counts: $SRC_COUNTS"

  docker exec -e PGPASSWORD="$DB_PASS" "$CONTAINER" \
    pg_dump -U "$DB_USER" -d "$DB_NAME" \
      --format=custom \
      --compress=9 \
      --blobs \
      --verbose \
      --no-password \
    > "$DUMP_FILE"

  DUMP_BYTES=$(wc -c < "$DUMP_FILE" | tr -d ' ')
  TOC_LINES=$(docker exec -i "$CONTAINER" pg_restore --list < "$DUMP_FILE" | wc -l | tr -d ' ')
  sha256sum "$DUMP_FILE" > "$CHECKSUM"

  log "Dump size: ${DUMP_BYTES} bytes, TOC entries: ${TOC_LINES}"
  log "Checksum: $(cat "$CHECKSUM")"
fi

# ── Restore to temp DB and compare 1:1 ───────────────────────────────────────
log "Creating verify database: $VERIFY_DB"
docker exec -e PGPASSWORD="$DB_PASS" "$CONTAINER" \
  psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS \"${VERIFY_DB}\";" >/dev/null
docker exec -e PGPASSWORD="$DB_PASS" "$CONTAINER" \
  psql -U "$DB_USER" -d postgres -c "CREATE DATABASE \"${VERIFY_DB}\" OWNER \"${DB_USER}\";" >/dev/null

cleanup() {
  docker exec -e PGPASSWORD="$DB_PASS" "$CONTAINER" \
    psql -U "$DB_USER" -d postgres -c "DROP DATABASE IF EXISTS \"${VERIFY_DB}\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "Restoring dump into $VERIFY_DB for verification..."
docker exec -i -e PGPASSWORD="$DB_PASS" "$CONTAINER" \
  pg_restore -U "$DB_USER" -d "$VERIFY_DB" --no-owner --no-acl --verbose \
  < "$DUMP_FILE" 2>&1 | tail -5

REST_COUNTS=$(count_rows "$VERIFY_DB")
log "Restored row counts: $REST_COUNTS"

if [[ "${VERIFY_ONLY:-0}" != "1" ]]; then
  SRC_COUNTS="${SRC_COUNTS:-}"
fi

if [[ -z "${SRC_COUNTS:-}" ]]; then
  SRC_COUNTS=$(count_rows "$DB_NAME")
fi

if [[ "$SRC_COUNTS" != "$REST_COUNTS" ]]; then
  log "ERROR: row counts mismatch!"
  log "  source:   $SRC_COUNTS"
  log "  restored: $REST_COUNTS"
  exit 1
fi

log "✓ Row counts match 1:1"

if [[ "${VERIFY_ONLY:-0}" != "1" ]]; then
  cat > "$MANIFEST" <<EOF
{
  "database": "${DB_NAME}",
  "container": "${CONTAINER}",
  "timestamp_utc": "${TIMESTAMP}",
  "dump_file": "$(basename "$DUMP_FILE")",
  "dump_bytes": ${DUMP_BYTES},
  "pg_restore_toc_entries": ${TOC_LINES},
  "sha256": "$(awk '{print $1}' "$CHECKSUM")",
  "row_counts": ${SRC_COUNTS},
  "verified_restore": true,
  "notes": "pg_dump -Fc --compress=9 --blobs; verified by full pg_restore to temp DB"
}
EOF
  log "Manifest: $MANIFEST"
  log "=== Backup OK ==="
fi

exit 0
