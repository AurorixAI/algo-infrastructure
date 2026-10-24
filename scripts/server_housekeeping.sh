#!/usr/bin/env bash
# Weekly server housekeeping (N5 / #136): free disk without touching anything a
# rollback needs.
#
#   1. docker build cache older than 7 days   (docker builder prune -af --filter until=168h)
#   2. release dumps: files directly in ~/release_dumps named *.sql.gz or *.dump
#      with mtime older than 14 days are deleted -- but ONLY if the nightly prod
#      backup is verified fresh (safety gate below). Everything else in that
#      directory (.jsonl, .sh, .txt, .tar.gz, subdirectories, ...) is never touched.
#   3. df -h / before and after
#
# Safety gate: the newest directory in NIGHTLY_DIR (YYYYMMDD names, written by
# /usr/local/sbin/algo-backup-prod.sh) must be at most NIGHTLY_MAX_AGE_DAYS old
# (by its name), contain SHA256SUMS and at least NIGHTLY_MIN_DUMPS non-empty
# *.dump files. If not: WARNING, no dump is deleted, the build cache is still
# pruned, exit 0 (cron must not spam).
#
# Never prunes images, containers, volumes or networks: rollback images
# (algolab-*:<tag>) must survive. Only the build CACHE is pruned.
#
# Usage:  scripts/server_housekeeping.sh [--dry-run]
#   --dry-run   print what would be deleted, delete nothing, run no prune.
#
# Environment (defaults suit the server; overrides exist for tests):
#   DUMP_DIR              directory with dumps   (default: $HOME/release_dumps)
#   NIGHTLY_DIR           nightly prod backups   (default: /home/algo/backups/prod_nightly)
#   KEEP_DAYS             age threshold, days    (default: 14)
#   NIGHTLY_MAX_AGE_DAYS  max age of newest nightly dir (default: 2)
#   NIGHTLY_MIN_DUMPS     required *.dump in it  (default: 4)
#   BUILD_CACHE_AGE       docker filter          (default: 168h)
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $arg (only --dry-run is supported)" >&2; exit 2 ;;
  esac
done

DUMP_DIR="${DUMP_DIR:-$HOME/release_dumps}"
NIGHTLY_DIR="${NIGHTLY_DIR:-/home/algo/backups/prod_nightly}"
KEEP_DAYS="${KEEP_DAYS:-14}"
NIGHTLY_MAX_AGE_DAYS="${NIGHTLY_MAX_AGE_DAYS:-2}"
NIGHTLY_MIN_DUMPS="${NIGHTLY_MIN_DUMPS:-4}"
BUILD_CACHE_AGE="${BUILD_CACHE_AGE:-168h}"

log() { printf '[housekeeping] %s\n' "$*"; }
[[ "$DRY_RUN" == 1 ]] && log "DRY RUN: nothing will be deleted"

log "disk before:"
df -h /

# ── 1. docker build cache ────────────────────────────────────────────────────
if [[ "$DRY_RUN" == 1 ]]; then
  log "would run: docker builder prune -af --filter until=$BUILD_CACHE_AGE"
elif command -v docker >/dev/null 2>&1; then
  log "docker builder prune -af --filter until=$BUILD_CACHE_AGE"
  docker builder prune -af --filter "until=$BUILD_CACHE_AGE"
else
  log "WARNING: docker not found, build cache not pruned"
fi

# ── 2. old release dumps (behind the nightly-backup gate) ───────────────────
# Prints the reason and returns non-zero when the newest nightly backup is not
# good enough to justify deleting old dumps.
nightly_gate() {
  local newest day cutoff n
  newest="$(cd "$NIGHTLY_DIR" 2>/dev/null && ls -1 | grep -E '^[0-9]{8}$' | sort | tail -n 1)" || true
  if [[ -z "$newest" || ! -d "$NIGHTLY_DIR/$newest" ]]; then
    echo "no YYYYMMDD directory in $NIGHTLY_DIR"; return 1
  fi
  day="$newest"
  # cutoff = today minus NIGHTLY_MAX_AGE_DAYS (GNU date, else BSD date)
  cutoff="$(date -d "$NIGHTLY_MAX_AGE_DAYS days ago" +%Y%m%d 2>/dev/null || date -v-"${NIGHTLY_MAX_AGE_DAYS}"d +%Y%m%d)"
  if [[ "$day" -lt "$cutoff" ]]; then
    echo "newest nightly backup $day is older than $NIGHTLY_MAX_AGE_DAYS days (cutoff $cutoff)"; return 1
  fi
  if [[ ! -s "$NIGHTLY_DIR/$newest/SHA256SUMS" ]]; then
    echo "$newest has no SHA256SUMS"; return 1
  fi
  n="$(find "$NIGHTLY_DIR/$newest" -maxdepth 1 -type f -name '*.dump' -size +0 | wc -l | tr -d ' ')"
  if (( n < NIGHTLY_MIN_DUMPS )); then
    echo "$newest has $n non-empty *.dump files, need $NIGHTLY_MIN_DUMPS"; return 1
  fi
  echo "newest nightly backup $newest OK ($n dumps, SHA256SUMS present)"
}

deleted=0
if gate_msg="$(nightly_gate)"; then
  log "gate passed: $gate_msg"
  if [[ -d "$DUMP_DIR" ]]; then
    while IFS= read -r path; do
      [[ -n "$path" ]] || continue
      if [[ "$DRY_RUN" == 1 ]]; then
        log "would delete: $path"
      else
        rm -f -- "$path"
        log "deleted: $path"
      fi
      deleted=$((deleted + 1))
    done < <(find "$DUMP_DIR" -maxdepth 1 -type f \( -name '*.sql.gz' -o -name '*.dump' \) -mtime +"$KEEP_DAYS" -print | sort)
  else
    log "dump directory $DUMP_DIR does not exist, nothing to do"
  fi
  if [[ "$DRY_RUN" == 1 ]]; then log "dumps that would be deleted: $deleted"; else log "dumps deleted: $deleted"; fi
else
  log "WARNING: nightly backup missing/stale ($gate_msg) -- dump cleanup skipped"
fi

log "disk after:"
df -h /
