#!/usr/bin/env bash
# Weekly server housekeeping (N5 / #136): free disk without touching anything a
# rollback needs.
#
#   1. docker build cache older than 7 days   (docker builder prune -af --filter until=168h)
#   2. release dumps: files directly in ~/release_dumps named *.sql.gz or *.dump
#      with mtime older than KEEP_DAYS (14) are deleted -- but ONLY if the nightly
#      prod backup is verified fresh (safety gate below). Everything else in that
#      directory (.jsonl, .sh, .txt, .tar.gz, symlinks, subdirectories, ...) is
#      never touched. Age is the file mtime (a copy made with `cp -p` keeps the
#      original mtime; a plain `cp` makes the dump look new).
#   3. df -h / before and after
#
# Safety gate: the newest directory in NIGHTLY_DIR by name (YYYYMMDD, written by
# /usr/local/sbin/algo-backup-prod.sh) must
#   - be a real directory (not a symlink) with a real calendar date in its name,
#   - be dated today or earlier, and at most NIGHTLY_MAX_AGE_DAYS ago,
#   - contain SHA256SUMS that verifies (`sha256sum -c --strict`, run inside that
#     dir; `shasum -a 256 -c` where sha256sum is missing) and lists at least
#     NIGHTLY_MIN_DUMPS files,
#   - contain at least NIGHTLY_MIN_DUMPS non-empty *.dump files.
# If not: WARNING, no dump is deleted, the build cache is still pruned, exit 0.
#
# Every step is independent: a failing `docker builder prune` or `rm` is a
# WARNING and the script carries on, always prints "disk after" and exits 0.
# Only bad arguments exit 2.
#
# Never prunes images, containers, volumes or networks: rollback images
# (algolab-*:<tag>) must survive. Only the build CACHE is pruned.
#
# Usage:  scripts/server_housekeeping.sh [--dry-run]
#   --dry-run   print what would be deleted, delete nothing, run no prune.
#
# Environment (defaults suit the server; overrides exist for tests):
#   DUMP_DIR              directory with dumps   (default: ${HOME:-/home/algo}/release_dumps)
#   NIGHTLY_DIR           nightly prod backups   (default: /home/algo/backups/prod_nightly)
#   KEEP_DAYS             age threshold, days    (default: 14, minimum 7)
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

log()  { printf '[housekeeping] %s\n' "$*"; }
warn() { printf '[housekeeping] WARNING: %s\n' "$*"; }

DUMP_DIR="${DUMP_DIR:-${HOME:-/home/algo}/release_dumps}"
NIGHTLY_DIR="${NIGHTLY_DIR:-/home/algo/backups/prod_nightly}"
KEEP_DAYS="${KEEP_DAYS:-14}"
NIGHTLY_MAX_AGE_DAYS="${NIGHTLY_MAX_AGE_DAYS:-2}"
NIGHTLY_MIN_DUMPS="${NIGHTLY_MIN_DUMPS:-4}"
BUILD_CACHE_AGE="${BUILD_CACHE_AGE:-168h}"

if ! [[ "$KEEP_DAYS" =~ ^[0-9]+$ ]]; then
  warn "KEEP_DAYS='$KEEP_DAYS' is not a number, using 14"; KEEP_DAYS=14
elif (( KEEP_DAYS < 7 )); then
  warn "KEEP_DAYS=$KEEP_DAYS is below the minimum, using 7"; KEEP_DAYS=7
fi
if ! [[ "$NIGHTLY_MAX_AGE_DAYS" =~ ^[0-9]+$ ]]; then
  warn "NIGHTLY_MAX_AGE_DAYS='$NIGHTLY_MAX_AGE_DAYS' is not a number, using 2"; NIGHTLY_MAX_AGE_DAYS=2
fi
if ! [[ "$NIGHTLY_MIN_DUMPS" =~ ^[0-9]+$ ]] || (( NIGHTLY_MIN_DUMPS < 1 )); then
  warn "NIGHTLY_MIN_DUMPS='$NIGHTLY_MIN_DUMPS' is invalid, using 4"; NIGHTLY_MIN_DUMPS=4
fi

[[ "$DRY_RUN" == 1 ]] && log "DRY RUN: nothing will be deleted"

log "disk before:"
df -h / || true

# ── 1. docker build cache ────────────────────────────────────────────────────
if [[ "$DRY_RUN" == 1 ]]; then
  log "would run: docker builder prune -af --filter until=$BUILD_CACHE_AGE"
elif command -v docker >/dev/null 2>&1; then
  log "docker builder prune -af --filter until=$BUILD_CACHE_AGE"
  if ! docker builder prune -af --filter "until=$BUILD_CACHE_AGE"; then
    warn "docker builder prune failed, continuing with dump cleanup"
  fi
else
  warn "docker not found, build cache not pruned"
fi

# ── 2. old release dumps (behind the nightly-backup gate) ───────────────────
# Real calendar date check: round-trips YYYYMMDD through date(1) (GNU, else BSD).
valid_date() {
  local d="$1" out
  out="$(date -d "${d:0:4}-${d:4:2}-${d:6:2}" +%Y%m%d 2>/dev/null || date -j -f %Y%m%d "$d" +%Y%m%d 2>/dev/null)" || return 1
  [[ "$out" == "$d" ]]
}

# SHA256SUMS must verify, run inside the directory (paths in it are relative).
verify_sums() {
  if command -v sha256sum >/dev/null 2>&1; then
    (cd "$1" && sha256sum -c --strict --quiet SHA256SUMS >/dev/null 2>&1)
  elif command -v shasum >/dev/null 2>&1; then
    (cd "$1" && shasum -a 256 -c SHA256SUMS >/dev/null 2>&1)
  else
    return 1
  fi
}

# Prints the verdict; returns non-zero when the newest nightly backup is not
# good enough to justify deleting old dumps.
nightly_gate() {
  local newest today cutoff n
  newest="$( { ls -1 "$NIGHTLY_DIR" 2>/dev/null || true; } | { grep -E '^[0-9]{8}$' || true; } | sort | tail -n 1 )"
  if [[ -z "$newest" ]]; then
    echo "no YYYYMMDD directory in $NIGHTLY_DIR"; return 1
  fi
  if [[ -L "$NIGHTLY_DIR/$newest" || ! -d "$NIGHTLY_DIR/$newest" ]]; then
    echo "$newest is a symlink or not a directory"; return 1
  fi
  if ! valid_date "$newest"; then
    echo "$newest is not a valid calendar date"; return 1
  fi
  today="$(date +%Y%m%d)"
  cutoff="$(date -d "$NIGHTLY_MAX_AGE_DAYS days ago" +%Y%m%d 2>/dev/null || date -v-"${NIGHTLY_MAX_AGE_DAYS}"d +%Y%m%d)"
  if (( 10#$newest > 10#$today )); then
    echo "newest nightly backup $newest is dated in the future (today $today)"; return 1
  fi
  if (( 10#$newest < 10#$cutoff )); then
    echo "newest nightly backup $newest is older than $NIGHTLY_MAX_AGE_DAYS days (cutoff $cutoff)"; return 1
  fi
  if [[ ! -s "$NIGHTLY_DIR/$newest/SHA256SUMS" ]]; then
    echo "$newest has no SHA256SUMS"; return 1
  fi
  if ! verify_sums "$NIGHTLY_DIR/$newest"; then
    echo "$newest: SHA256SUMS does not verify"; return 1
  fi
  n="$(grep -c . "$NIGHTLY_DIR/$newest/SHA256SUMS" || true)"
  if (( n < NIGHTLY_MIN_DUMPS )); then
    echo "$newest: SHA256SUMS lists only $n files, need $NIGHTLY_MIN_DUMPS"; return 1
  fi
  n="$(find "$NIGHTLY_DIR/$newest" -maxdepth 1 -type f -name '*.dump' -size +0 | wc -l | tr -d ' ')"
  if (( n < NIGHTLY_MIN_DUMPS )); then
    echo "$newest has $n non-empty *.dump files, need $NIGHTLY_MIN_DUMPS"; return 1
  fi
  echo "newest nightly backup $newest OK ($n dumps, SHA256SUMS verified)"
}

deleted=0
failed=0
if gate_msg="$(nightly_gate)"; then
  log "gate passed: $gate_msg"
  if [[ -d "$DUMP_DIR" ]]; then
    # NUL-separated, so any file name is safe.
    while IFS= read -r -d '' path; do
      if [[ "$DRY_RUN" == 1 ]]; then
        log "would delete: $path"
        deleted=$((deleted + 1))
      elif rm -f -- "$path"; then
        log "deleted: $path"
        deleted=$((deleted + 1))
      else
        warn "could not delete $path, continuing"
        failed=$((failed + 1))
      fi
    done < <(find "$DUMP_DIR" -maxdepth 1 -type f \( -name '*.sql.gz' -o -name '*.dump' \) -mtime +"$KEEP_DAYS" -print0 | sort -z)
  else
    log "dump directory $DUMP_DIR does not exist, nothing to do"
  fi
  if [[ "$DRY_RUN" == 1 ]]; then log "dumps that would be deleted: $deleted"; else log "dumps deleted: $deleted"; fi
  if (( failed > 0 )); then warn "$failed dump(s) could not be deleted"; fi
else
  warn "nightly backup missing/stale ($gate_msg) -- dump cleanup skipped"
fi

log "disk after:"
df -h / || true
exit 0
