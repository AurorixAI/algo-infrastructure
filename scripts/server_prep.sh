#!/usr/bin/env bash
# ==============================================================================
# ALGO — server preparation (swap, docker log rotation, cleanup + backup cron)
#
# Run on the Hetzner host as root. Idempotent: safe to re-run.
#
#   sudo ./algo-infrastructure/scripts/server_prep.sh                   # prepare
#   sudo ./algo-infrastructure/scripts/server_prep.sh --restart-docker  # + restart dockerd
#
# What it does:
#   a. 4G /swapfile (+ /etc/fstab) and vm.swappiness=10 (/etc/sysctl.d/99-algo.conf)
#   b. /etc/docker/daemon.json: json-file log driver, max-size 10m, max-file 3
#      (merged into existing JSON, .bak kept). dockerd is restarted ONLY with
#      --restart-docker — a restart stops/starts ALL containers (prod + stage).
#   c. /etc/cron.d/algo-maintenance:
#        04:30  docker image prune -f ; docker builder prune -f --filter until=72h
#        03:30  prod content DB backup (algo-staging-content-db), keep 14 days
#
# Overridable env vars: ALGO_USER (default algo), ALGO_ROOT (default ~ALGO_USER/algo),
#   BACKUP_DIR (default ~ALGO_USER/backups/algo_content), SWAP_SIZE (default 4G),
#   PROD_CONTENT_CONTAINER (default algo-staging-content-db),
#   PROD_ENV_FILE (default $ALGO_ROOT/.env.staging), BACKUP_KEEP_DAYS (default 14).
# ==============================================================================
set -euo pipefail

RESTART_DOCKER=0
for arg in "$@"; do
  case "$arg" in
    --restart-docker) RESTART_DOCKER=1 ;;
    -h|--help) sed -n '2,23p' "$0"; exit 0 ;;
    *) echo "Unknown argument: $arg (see --help)" >&2; exit 2 ;;
  esac
done

log() { echo "[server_prep] $*"; }

if [[ $EUID -ne 0 ]]; then
  echo "Must be run as root: sudo $0 $*" >&2
  exit 1
fi

SWAP_SIZE="${SWAP_SIZE:-4G}"
SWAPFILE=/swapfile
ALGO_USER="${ALGO_USER:-algo}"
if ! id "$ALGO_USER" >/dev/null 2>&1; then
  echo "User '$ALGO_USER' does not exist (set ALGO_USER=...)" >&2
  exit 1
fi
ALGO_HOME="$(getent passwd "$ALGO_USER" | cut -d: -f6)"
ALGO_ROOT="${ALGO_ROOT:-$ALGO_HOME/algo}"
BACKUP_SCRIPT="$ALGO_ROOT/algo-infrastructure/scripts/backup_algo_content.sh"
BACKUP_DIR="${BACKUP_DIR:-$ALGO_HOME/backups/algo_content}"
PROD_CONTAINER="${PROD_CONTENT_CONTAINER:-algo-staging-content-db}"
PROD_ENV_FILE="${PROD_ENV_FILE:-$ALGO_ROOT/.env.staging}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
STATE_DIR=/var/lib/algo
mkdir -p "$STATE_DIR"

# ── a. swap + swappiness ─────────────────────────────────────────────────────
log "== a. swap ($SWAP_SIZE at $SWAPFILE) =="
if [[ ! -e "$SWAPFILE" ]]; then
  log "creating $SWAPFILE"
  if ! fallocate -l "$SWAP_SIZE" "$SWAPFILE" 2>/dev/null; then
    log "fallocate failed, falling back to dd"
    dd if=/dev/zero of="$SWAPFILE" bs=1M count=$(( ${SWAP_SIZE%G} * 1024 )) status=none
  fi
  chmod 600 "$SWAPFILE"
  mkswap "$SWAPFILE" >/dev/null
else
  log "$SWAPFILE already exists"
  chmod 600 "$SWAPFILE"
fi
if ! swapon --show=NAME --noheadings | grep -qx "$SWAPFILE"; then
  log "enabling $SWAPFILE"
  swapon "$SWAPFILE"
else
  log "$SWAPFILE already active"
fi
if ! grep -qE "^[[:space:]]*$SWAPFILE[[:space:]]" /etc/fstab; then
  log "adding fstab entry"
  echo "$SWAPFILE none swap sw 0 0" >> /etc/fstab
else
  log "fstab entry present"
fi
SYSCTL_FILE=/etc/sysctl.d/99-algo.conf
if [[ "$(cat "$SYSCTL_FILE" 2>/dev/null)" != "vm.swappiness=10" ]]; then
  log "writing $SYSCTL_FILE"
  echo "vm.swappiness=10" > "$SYSCTL_FILE"
fi
sysctl -q -w vm.swappiness=10

# ── b. docker log rotation ───────────────────────────────────────────────────
log "== b. /etc/docker/daemon.json (json-file, max-size 10m, max-file 3) =="
DAEMON_JSON=/etc/docker/daemon.json
mkdir -p /etc/docker
DAEMON_CHANGED=$(DAEMON_JSON="$DAEMON_JSON" python3 - <<'PY'
import json, os, shutil, sys
path = os.environ["DAEMON_JSON"]
cfg = {}
if os.path.exists(path) and os.path.getsize(path) > 0:
    with open(path) as f:
        try:
            cfg = json.load(f)
        except ValueError as e:
            sys.stderr.write("ERROR: %s is not valid JSON (%s); fix it manually\n" % (path, e))
            sys.exit(1)
    if not isinstance(cfg, dict):
        sys.stderr.write("ERROR: %s is not a JSON object\n" % path)
        sys.exit(1)
orig = json.dumps(cfg, sort_keys=True)
cfg["log-driver"] = "json-file"
opts = cfg.get("log-opts") if isinstance(cfg.get("log-opts"), dict) else {}
opts.update({"max-size": "10m", "max-file": "3"})
cfg["log-opts"] = opts
if json.dumps(cfg, sort_keys=True) == orig:
    print("0")
else:
    if os.path.exists(path):
        shutil.copy2(path, path + ".bak")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    print("1")
PY
)
if [[ "$DAEMON_CHANGED" == "1" ]]; then
  log "daemon.json updated (previous version saved as $DAEMON_JSON.bak)"
  touch "$STATE_DIR/docker-restart-pending"
else
  log "daemon.json already has the desired log settings"
fi
if [[ -e "$STATE_DIR/docker-restart-pending" ]]; then
  if [[ $RESTART_DOCKER -eq 1 ]]; then
    log "WARNING: restarting docker — ALL containers (prod + stage) will restart; expect a short outage"
    sleep 5
    systemctl restart docker
    rm -f "$STATE_DIR/docker-restart-pending"
    log "docker restarted"
  else
    log "NOTE: docker restart needed for the new log settings. Re-run with --restart-docker"
    log "      (restarts ALL containers). Log options apply only to containers created afterwards"
    log "      (e.g. after 'docker compose up -d --force-recreate' or the next deploy)."
  fi
fi

# ── c/d. cron: cleanup + prod content DB backup ──────────────────────────────
log "== c/d. cron =="
WRAPPER=/usr/local/sbin/algo-backup-content.sh
{
  echo '#!/usr/bin/env bash'
  echo '# Generated by server_prep.sh — daily prod content DB backup with retention.'
  echo 'set -euo pipefail'
  printf 'BACKUP_SCRIPT=%q\nBACKUP_DIR=%q\nENV_FILE=%q\nCONTAINER=%q\nKEEP_DAYS=%q\n' \
    "$BACKUP_SCRIPT" "$BACKUP_DIR" "$PROD_ENV_FILE" "$PROD_CONTAINER" "$KEEP_DAYS"
  cat <<'BODY'
# POSTGRES_PASSWORD is read from the prod env file (not sourced: avoids shell-parsing the whole file)
PW="$(grep -E '^POSTGRES_PASSWORD=' "$ENV_FILE" | tail -n1 | cut -d= -f2- | sed -E "s/^'(.*)'\$/\1/; s/^\"(.*)\"\$/\1/")"
[[ -n "$PW" ]] || { echo "POSTGRES_PASSWORD not found in $ENV_FILE" >&2; exit 1; }
export CONTENT_PG_CONTAINER="$CONTAINER" POSTGRES_USER=algo POSTGRES_DB=algo_content POSTGRES_PASSWORD="$PW"
mkdir -p "$BACKUP_DIR"
"$BACKUP_SCRIPT" "$BACKUP_DIR"
# retention only after a successful backup (set -e): dump + manifest + sha256 older than KEEP_DAYS
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'algo_content_*' -mtime +"$KEEP_DAYS" -delete
BODY
} > "$WRAPPER.new"
chmod 755 "$WRAPPER.new"
if ! cmp -s "$WRAPPER.new" "$WRAPPER" 2>/dev/null; then
  mv "$WRAPPER.new" "$WRAPPER"
  log "wrote $WRAPPER"
else
  rm -f "$WRAPPER.new"
  log "$WRAPPER up to date"
fi
mkdir -p "$BACKUP_DIR"
chown "$ALGO_USER": "$BACKUP_DIR"
[[ -x "$BACKUP_SCRIPT" ]] || log "WARNING: $BACKUP_SCRIPT missing or not executable (git pull in $ALGO_ROOT/algo-infrastructure; chmod +x)"
[[ -r "$PROD_ENV_FILE" ]] || log "WARNING: $PROD_ENV_FILE not found — backup cron will fail until it exists"

CRON_FILE=/etc/cron.d/algo-maintenance
CRON_TMP="$(mktemp)"
cat > "$CRON_TMP" <<CRON
# Managed by algo-infrastructure/scripts/server_prep.sh — do not edit by hand
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
30 3 * * * $ALGO_USER $WRAPPER >> /var/log/algo-backup.log 2>&1
30 4 * * * root docker image prune -f >> /var/log/algo-maintenance.log 2>&1 && docker builder prune -f --filter until=72h >> /var/log/algo-maintenance.log 2>&1
CRON
if ! cmp -s "$CRON_TMP" "$CRON_FILE" 2>/dev/null; then
  install -m 644 -o root -g root "$CRON_TMP" "$CRON_FILE"
  log "wrote $CRON_FILE"
else
  log "$CRON_FILE up to date"
fi
rm -f "$CRON_TMP"

# log files: keep small (backup log is written by $ALGO_USER, cleanup log by root)
touch /var/log/algo-backup.log /var/log/algo-maintenance.log
chown "$ALGO_USER": /var/log/algo-backup.log
cat > /etc/logrotate.d/algo-maintenance <<'LR'
/var/log/algo-backup.log /var/log/algo-maintenance.log {
    weekly
    rotate 4
    compress
    missingok
    notifempty
    copytruncate
}
LR

# ── e. summary ───────────────────────────────────────────────────────────────
log "== summary =="
echo "--- free -h";        free -h
echo "--- swapon --show";  swapon --show
echo "--- df -h /";        df -h /
echo "--- vm.swappiness";  sysctl -n vm.swappiness
echo "--- cron";           cat "$CRON_FILE" | grep -v '^#'
if [[ -e "$STATE_DIR/docker-restart-pending" ]]; then
  echo "--- PENDING: docker restart required (re-run with --restart-docker)"
fi
log "done"
