#!/usr/bin/env bash
# Starts the dev compose stack and creates the e2e test administrator with backend/scripts/create_admin.py.
#   bash e2e/scripts/setup-e2e.sh            # idempotent
#   bash e2e/scripts/setup-e2e.sh --fresh    # wipe the dev DB/volumes first (docker compose down -v)
# The admin password is generated randomly, passed to the script through the environment (never argv), and saved
# only in e2e/.e2e.env (gitignored). Override with E2E_ADMIN_USERNAME / E2E_ADMIN_PASSWORD.
set -euo pipefail

E2E_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(cd "$E2E_DIR/.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/deploy/docker-compose.dev.yml")
ENV_FILE="$E2E_DIR/.e2e.env"

if [ "${1:-}" = "--fresh" ]; then
  "${COMPOSE[@]}" down -v --remove-orphans
  rm -f "$ENV_FILE"
fi

echo "[e2e] starting dev stack (build on first run takes several minutes)"
"${COMPOSE[@]}" up -d --build --wait

USERNAME="${E2E_ADMIN_USERNAME:-e2e.admin}"
if [ -n "${E2E_ADMIN_PASSWORD:-}" ]; then
  PASSWORD="$E2E_ADMIN_PASSWORD"
elif [ -f "$ENV_FILE" ] && grep -q '^E2E_ADMIN_PASSWORD=' "$ENV_FILE"; then
  PASSWORD="$(grep '^E2E_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
else
  PASSWORD="$(node -e "console.log(require('node:crypto').randomBytes(18).toString('base64url'))")"
fi

echo "[e2e] creating test admin '$USERNAME' (backend/scripts/create_admin.py)"
export CREATE_ADMIN_PASSWORD="$PASSWORD"
if "${COMPOSE[@]}" exec -T -e CREATE_ADMIN_PASSWORD api python scripts/create_admin.py \
    --username "$USERNAME" --full-name "E2E Administrator"; then
  :
else
  if [ -f "$ENV_FILE" ]; then
    echo "[e2e] admin already exists - reusing credentials from $ENV_FILE"
    PASSWORD="$(grep '^E2E_ADMIN_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)"
  else
    echo "[e2e] ERROR: admin exists but no saved credentials; run with --fresh or pass E2E_ADMIN_PASSWORD" >&2
    exit 1
  fi
fi
unset CREATE_ADMIN_PASSWORD

umask 077
{
  echo "E2E_BASE_URL=${E2E_BASE_URL:-http://localhost:8080}"
  echo "E2E_ADMIN_USERNAME=$USERNAME"
  echo "E2E_ADMIN_PASSWORD=$PASSWORD"
} > "$ENV_FILE"
echo "[e2e] ready. credentials saved in e2e/.e2e.env (gitignored). Run:  cd e2e && pnpm install && pnpm exec playwright install chromium && pnpm test"
