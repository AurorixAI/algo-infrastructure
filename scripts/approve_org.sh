#!/usr/bin/env bash
# ALGO — Superadmin CLI: review & approve/reject pending organization applications.
#
# Registration never logs an org straight in — apply_organization() creates it
# with status=pending and the owner is_active=False. This script is the
# (temporary, pre-admin-panel) way to review a pending application and either
# approve it (activates the org + owner immediately — the owner can then log
# in with the password they registered with, no separate confirmation step)
# or reject it.
#
# Usage:
#   ./approve_org.sh list
#   ./approve_org.sh approve <org_id>
#   ./approve_org.sh reject  <org_id> ["reason"]
#
# Env overrides (defaults match local dev — see root Makefile):
#   COMPOSE_FILE=docker-compose.staging.yml PROJECT_NAME=algo-staging ./approve_org.sh list

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.local.yml}"
PROJECT_NAME="${PROJECT_NAME:-algo}"

DC=(docker compose -f "$COMPOSE_FILE" -p "$PROJECT_NAME")

run_py() {
  # Reads the python source from this function's stdin (a quoted heredoc at
  # each call site — quoted so bash does zero expansion/escaping of it).
  # ORG_ID / REJECT_REASON are passed through as env vars, never interpolated
  # into the python source itself.
  (cd "$ROOT_DIR" && "${DC[@]}" exec -T \
    -e ORG_ID="${ORG_ID:-}" -e REJECT_REASON="${REJECT_REASON:-}" \
    auth-service python3 -)
}

cmd="${1:-}"

case "$cmd" in
  list)
    run_py <<'PYEOF'
from src.core.database import SessionLocal
from src.models.auth import Organization, User

db = SessionLocal()
orgs = (
    db.query(Organization)
    .filter(Organization.status == "pending")
    .order_by(Organization.created_at)
    .all()
)

if not orgs:
    print("Нет организаций, ожидающих решения.")
else:
    dash = "-"
    print(f"Ждут решения администратора: {len(orgs)}\n")
    for org in orgs:
        owner = db.query(User).filter(User.id == org.owner_id).first()
        print("=" * 64)
        print(f"  ID:        {org.id}")
        print(f"  Название:  {org.name}")
        print(f"  Тип:       {org.org_type or dash}")
        print(f"  Город:     {org.city or dash}")
        print(f"  Телефон:   {org.phone or dash}")
        print(f"  Email:     {org.email or dash}")
        print(f"  Подана:    {org.created_at}")
        if owner:
            print(f"  Владелец:  {owner.full_name} <{owner.email}>")
    print("=" * 64)
    print()
    print("Одобрить:  ./approve_org.sh approve <ID>  (владелец сможет войти сразу)")
    print("Отклонить: ./approve_org.sh reject <ID> \"причина\"")
db.close()
PYEOF
    ;;

  approve)
    ORG_ID="${2:?Использование: approve_org.sh approve <org_id>}"
    run_py <<'PYEOF'
import os
from src.core.database import SessionLocal
from src.auth.service import AuthService

org_id = os.environ["ORG_ID"]
db = SessionLocal()
try:
    result = AuthService(db).approve_organization(org_id, action="approve")
    owner_email = result["owner_email"]
    print("✓ Организация активирована:", result["org_id"])
    print(f"  Владелец уже может войти: {owner_email} (со своим паролем при регистрации)")
except ValueError as e:
    print(f"ОШИБКА: {e}")
    raise SystemExit(1)
finally:
    db.close()
PYEOF
    ;;

  reject)
    ORG_ID="${2:?Использование: approve_org.sh reject <org_id> [reason]}"
    REJECT_REASON="${3:-Отклонено администратором}"
    run_py <<'PYEOF'
import os
from src.core.database import SessionLocal
from src.auth.service import AuthService

org_id = os.environ["ORG_ID"]
reason = os.environ.get("REJECT_REASON") or None
db = SessionLocal()
try:
    result = AuthService(db).approve_organization(org_id, action="reject", rejection_reason=reason)
    print("✗ Заявка отклонена:", result["org_id"])
except ValueError as e:
    print(f"ОШИБКА: {e}")
    raise SystemExit(1)
finally:
    db.close()
PYEOF
    ;;

  *)
    echo "Usage: $0 {list|approve <org_id>|reject <org_id> [reason]}"
    exit 1
    ;;
esac
