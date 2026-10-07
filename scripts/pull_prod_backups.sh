#!/bin/bash
# Off-server copy of the nightly production DB backups (free alternative to paid backups).
# Runs on the owner's Mac via launchd (me.algolab.backup-pull).
#  1. mirrors ~/backups/prod_nightly from the server into $ROOT/.mirror (raw, verified by SHA256SUMS);
#  2. presents every backup as "$ROOT/prod/<YYYY-MM-DD HH-MM>/prod_<db>_<YYYY-MM-DD_HH-MM>.dump"
#     (hard links, no extra disk) and writes $ROOT/prod/СПИСОК_БЭКАПОВ.txt;
#  3. keeps the last 30 days.
set -euo pipefail
SERVER="algo@91.99.183.252"
ROOT="${ALGO_BACKUP_ROOT:-$HOME/algolab-backups}"
MIRROR="$ROOT/.mirror"
OUT="$ROOT/prod"
LOG="$ROOT/pull.log"
mkdir -p "$MIRROR" "$OUT"
exec >>"$LOG" 2>&1
echo "=== $(date '+%F %T') pull start"
rsync -a --delete --timeout=120 -e "ssh -o BatchMode=yes -o ConnectTimeout=20" "$SERVER:backups/prod_nightly/" "$MIRROR/"

bad=0
index="$OUT/СПИСОК_БЭКАПОВ.txt.tmp"
{
  echo "Бэкапы базы данных прода algolab.me (копия с сервера на этот Mac)"
  echo "Обновлено: $(date '+%d.%m.%Y %H:%M')   Хранится: последние 30 дней"
  echo "Каждая папка = один ночной бэкап; в имени — дата и время создания на сервере (Ташкент)."
  echo "Файлы: content = банк задач, diagnostic = диагностики и ответы, exam = экзамены, auth = пользователи и ученики."
  echo
  printf '%-18s %-10s %s\n' "Дата и время" "Проверка" "Размеры (content / diagnostic / exam / auth)"
} > "$index"

for d in $(ls -d "$MIRROR"/2*/ 2>/dev/null | sort -r); do
  [ -f "$d/SHA256SUMS" ] || continue
  if (cd "$d" && shasum -a 256 -c SHA256SUMS >/dev/null 2>&1); then ok="OK"; else ok="ОШИБКА"; bad=1; fi
  stamp=$(date -r "$d/SHA256SUMS" '+%Y-%m-%d_%H-%M')
  human=$(date -r "$d/SHA256SUMS" '+%d.%m.%Y %H:%M')
  folder="$OUT/$(date -r "$d/SHA256SUMS" '+%Y-%m-%d %H-%M')"
  mkdir -p "$folder"
  sizes=""
  for db in content diagnostic exam auth; do
    src="$d/algo-staging-$db-db.dump"
    [ -f "$src" ] || { sizes="$sizes / —"; continue; }
    ln -f "$src" "$folder/prod_${db}_${stamp}.dump"
    sizes="$sizes / $(du -h "$src" | cut -f1 | tr -d ' ')"
  done
  cp -f "$d/SHA256SUMS" "$folder/SHA256SUMS_исходные_имена.txt"
  printf '%-18s %-10s %s\n' "$human" "$ok" "${sizes# / }" >> "$index"
done
{
  echo
  echo "Восстановление: остановить сервисы, DROP/CREATE DATABASE, затем pg_restore --single-transaction нужного файла."
  echo "Подробно: algo-infrastructure/docs/releases/PROD_RELEASE_PLAN.md, раздел «Откат»."
} >> "$index"
mv -f "$index" "$OUT/СПИСОК_БЭКАПОВ.txt"

# retention: presented folders older than 30 days (the mirror is pruned by the server's own 14-day retention via --delete)
find "$OUT" -mindepth 1 -maxdepth 1 -type d -mtime +30 -exec rm -rf {} +
echo "=== $(date '+%F %T') pull done, backups=$(ls -d "$OUT"/2*/ 2>/dev/null | wc -l | tr -d ' ') bad=$bad"
exit $bad
