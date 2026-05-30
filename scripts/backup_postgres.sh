#!/usr/bin/env bash
# ==============================================================================
# ALGO — PostgreSQL backup script
# Dumps all 4 databases, uploads to GCS, applies 30-day retention
#
# SETUP:
#   1. Set environment variables (or create /opt/algo/.backup.env):
#        GCS_BUCKET=gs://algo-backups-<project>
#        POSTGRES_PASSWORD=<shared_db_password>
#
#   2. Ensure gcloud is authenticated on VM:
#        gcloud auth application-default login
#      OR use a service account key:
#        export GOOGLE_APPLICATION_CREDENTIALS=/opt/algo/sa-key.json
#
#   3. Install on cron (runs daily at 03:00 server time):
#        echo "0 3 * * * root /opt/algo/scripts/backup_postgres.sh >> /var/log/algo-backup.log 2>&1" \
#          > /etc/cron.d/algo-pg-backup
#        chmod 644 /etc/cron.d/algo-pg-backup
#
#   4. Set GCS lifecycle (30-day auto-delete) — run ONCE:
#        gsutil lifecycle set /opt/algo/scripts/gcs-lifecycle.json gs://algo-backups-<project>
# ==============================================================================

set -euo pipefail

# ── Load env ──────────────────────────────────────────────────────────────────
ENV_FILE="${ENV_FILE:-/opt/algo/.backup.env}"
if [[ -f "$ENV_FILE" ]]; then
  # shellcheck source=/dev/null
  source "$ENV_FILE"
fi

: "${GCS_BUCKET:?GCS_BUCKET is required (e.g. gs://algo-backups-algo-495713)}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"

# ── Config ────────────────────────────────────────────────────────────────────
TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
BACKUP_DIR="/tmp/algo-pg-backups/${TIMESTAMP}"
POSTGRES_USER="${POSTGRES_USER:-algo}"

# Map: database_name → container_name
declare -A DB_CONTAINERS=(
  ["algo_auth"]="algo-postgres"
  ["algo_diagnostic"]="algo-postgres-diag"
  ["algo_exam"]="algo-postgres-exam"
  ["algo_content"]="content-postgres"
)

# ── Functions ─────────────────────────────────────────────────────────────────
log() { echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*"; }

dump_db() {
  local db_name="$1"
  local container="$2"
  local out_file="${BACKUP_DIR}/${db_name}_${TIMESTAMP}.sql.gz"

  log "Dumping ${db_name} from container ${container}..."
  docker exec -e PGPASSWORD="${POSTGRES_PASSWORD}" "${container}" \
    pg_dump -U "${POSTGRES_USER}" -d "${db_name}" --no-password \
    | gzip -9 > "${out_file}"

  local size
  size=$(du -sh "${out_file}" | cut -f1)
  log "  ✓ ${out_file} (${size})"
}

upload_to_gcs() {
  local db_name="$1"
  local file="${BACKUP_DIR}/${db_name}_${TIMESTAMP}.sql.gz"
  local gcs_path="${GCS_BUCKET}/${db_name}/${TIMESTAMP}/${db_name}_${TIMESTAMP}.sql.gz"

  log "Uploading ${db_name} → ${gcs_path}..."
  gsutil -q cp "${file}" "${gcs_path}"
  log "  ✓ Uploaded"
}

# ── Main ──────────────────────────────────────────────────────────────────────
log "=== ALGO PostgreSQL Backup Started ==="
mkdir -p "${BACKUP_DIR}"

EXIT_CODE=0

for db_name in "${!DB_CONTAINERS[@]}"; do
  container="${DB_CONTAINERS[$db_name]}"
  if ! docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
    log "WARNING: Container ${container} not running — skipping ${db_name}"
    continue
  fi

  if dump_db "${db_name}" "${container}"; then
    upload_to_gcs "${db_name}" || { log "ERROR: Upload failed for ${db_name}"; EXIT_CODE=1; }
  else
    log "ERROR: Dump failed for ${db_name}"
    EXIT_CODE=1
  fi
done

# ── Cleanup local temp files ───────────────────────────────────────────────────
rm -rf "${BACKUP_DIR}"
log "Cleaned up local temp dir"

log "=== ALGO PostgreSQL Backup Finished (exit=${EXIT_CODE}) ==="
exit ${EXIT_CODE}
