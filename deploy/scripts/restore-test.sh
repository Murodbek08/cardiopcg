#!/usr/bin/env bash
# Restore test: decrypts the LATEST pg dump into a throw-away, network-less postgres container and runs sanity queries.
# Needs the age PRIVATE key (it is deliberately not stored on the server):
#   RESTORE_AGE_IDENTITY=/path/to/key.txt deploy/scripts/restore-test.sh [path/to/pg-YYYY-MM-DD-HHMM.dump.age]
# Run it on the operator machine against a copied backup, or on the server with a temporarily provided key.
# Creates/removes ONLY the container `cardiopcg-restoretest`; production containers/volumes are never touched.
set -euo pipefail
umask 077

ROOT="${DEPLOY_ROOT:-/opt/cardiopcg}"
DIR="${BACKUP_DIR:-$ROOT/backups}"
IDENT="${RESTORE_AGE_IDENTITY:?set RESTORE_AGE_IDENTITY to the age private key file}"
[ -f "$IDENT" ] || { echo "identity file not found" >&2; exit 1; }
DUMP="${1:-$(ls -1t "$DIR"/pg-*.dump.age 2>/dev/null | head -1)}"
[ -n "$DUMP" ] && [ -f "$DUMP" ] || { echo "no pg-*.dump.age found in $DIR" >&2; exit 1; }
command -v age >/dev/null || { echo "age is not installed" >&2; exit 1; }

NAME=cardiopcg-restoretest
TMP_PW="$(openssl rand -hex 16)"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

echo "[restore-test] dump: $(basename "$DUMP")"
docker run -d --name "$NAME" --network none --label project=cardiopcg --memory 1g --cpus 1 \
  -e POSTGRES_PASSWORD="$TMP_PW" postgres:17-alpine >/dev/null
for _ in $(seq 1 30); do
  docker exec "$NAME" pg_isready -U postgres >/dev/null 2>&1 && break
  sleep 2
done
docker exec "$NAME" pg_isready -U postgres >/dev/null

age -d -i "$IDENT" "$DUMP" | docker exec -i "$NAME" pg_restore -U postgres -d postgres --create --no-owner --exit-on-error
DB="$(docker exec "$NAME" psql -U postgres -Atc "select datname from pg_database where datname not in ('postgres','template0','template1') limit 1")"
[ -n "$DB" ] || { echo "FAIL: no database restored" >&2; exit 1; }

q() { docker exec "$NAME" psql -U postgres -d "$DB" -Atc "$1"; }
users="$(q 'select count(*) from users')"
exams="$(q 'select count(*) from examinations')"
last_exam="$(q 'select coalesce(max(created_at)::text, '"'none'"') from examinations')"
last_audit="$(q 'select coalesce(max(ts)::text, '"'none'"') from audit_logs')"
echo "[restore-test] db=$DB users=$users examinations=$exams last_exam=$last_exam last_audit=$last_audit"

if [ "$users" -lt 1 ]; then echo "FAIL: users table is empty after restore" >&2; exit 1; fi
echo "[restore-test] OK"
