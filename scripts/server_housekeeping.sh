#!/usr/bin/env bash
# Weekly server housekeeping (N5 / #136): free disk without touching anything a
# rollback needs.
#
#   1. docker build cache older than 7 days   (docker builder prune -af --filter until=168h)
#   2. release dumps  ~/release_dumps/*.sql.gz older than 14 days, EXCEPT the
#      two newest dumps of every prefix (prod_auth, prod_exam, ...)
#   3. df -h / before and after
#
# Never prunes images, containers, volumes or networks: rollback images
# (algolab-*:<tag>) must survive. Only the build CACHE is pruned.
#
# Usage:  scripts/server_housekeeping.sh [--dry-run]
#   --dry-run   print what would be deleted, delete nothing, run no prune.
#
# Environment (defaults suit the server; overrides exist for tests):
#   DUMP_DIR     directory with dumps        (default: $HOME/release_dumps)
#   KEEP_DAYS    age threshold in days       (default: 14)
#   KEEP_NEWEST  newest dumps kept/prefix    (default: 2)
#   BUILD_CACHE_AGE  docker filter           (default: 168h)
#
# Prefix of a dump = file name up to the first "_" or "-" followed by an
# 8-digit date, e.g. prod_auth_20261010_0300.sql.gz -> "prod_auth". A file with
# no such date has no prefix group and is never deleted.
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
KEEP_DAYS="${KEEP_DAYS:-14}"
KEEP_NEWEST="${KEEP_NEWEST:-2}"
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

# ── 2. old release dumps ─────────────────────────────────────────────────────
# awk (not bash 4 arrays) so the same script runs on the server and in a macOS
# test. Input: file names newest-first (mtime). Output per line: "keep|old<TAB>name".
# "old" = not among the KEEP_NEWEST newest of its prefix; age is checked below.
deleted=0
if [[ -d "$DUMP_DIR" ]]; then
  verdicts="$(cd "$DUMP_DIR" && { ls -1t -- *.sql.gz 2>/dev/null || true; } | awk -v keep="$KEEP_NEWEST" '
    {
      prefix = $0
      if (!sub(/[_-][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].*$/, "", prefix)) { print "nogroup\t" $0; next }
      n[prefix]++
      print ((n[prefix] <= keep) ? "newest\t" : "candidate\t") $0
    }')"
  while IFS=$'\t' read -r verdict name; do
    [[ -n "${name:-}" ]] || continue
    case "$verdict" in
      nogroup) log "keep (no date in name, not grouped): $name" ;;
      newest)  log "keep (one of the $KEEP_NEWEST newest of its prefix): $name" ;;
      candidate)
        path="$DUMP_DIR/$name"
        # -mtime +N: strictly older than N full days. Portable (GNU and BSD find).
        if [[ -n "$(find "$path" -maxdepth 0 -type f -mtime +"$KEEP_DAYS" -print)" ]]; then
          if [[ "$DRY_RUN" == 1 ]]; then
            log "would delete: $path"
          else
            rm -f -- "$path"
            log "deleted: $path"
          fi
          deleted=$((deleted + 1))
        else
          log "keep (younger than $KEEP_DAYS days): $name"
        fi ;;
    esac
  done <<< "$verdicts"
else
  log "dump directory $DUMP_DIR does not exist, nothing to do"
fi
if [[ "$DRY_RUN" == 1 ]]; then log "dumps that would be deleted: $deleted"; else log "dumps deleted: $deleted"; fi

log "disk after:"
df -h /
