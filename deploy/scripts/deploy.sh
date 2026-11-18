#!/usr/bin/env bash
# CardioPCG AI - deploy to the shared server. Runs on YOUR machine / CI, talks to the server over SSH (key auth only).
#
#   DEPLOY_HOST=deploy@<server-ip> deploy/scripts/deploy.sh              # deploy HEAD
#   DEPLOY_HOST=deploy@<server-ip> deploy/scripts/deploy.sh --rollback   # back to the previous release
#   DEPLOY_HOST=... deploy/scripts/deploy.sh --rollback <sha>            # back to a specific release
#
# Env:
#   DEPLOY_HOST            required, e.g. deploy@164.68.111.41 (never a password; use an ssh key / agent)
#   DEPLOY_SSH_KEY         optional path to the private key (else ssh-agent / default keys)
#   DEPLOY_KNOWN_HOSTS     optional known_hosts file (host key pinned, StrictHostKeyChecking=yes always)
#   DEPLOY_ROOT            default /opt/cardiopcg  (releases/, shared/.env, current -> release)
#   OTHER_SITES            space-separated URLs of OTHER sites on the server, checked before and after
#   PRE_DEPLOY_BACKUP=1    run backup.sh on the server before migrating (recommended when migrations are destructive)
#   ALLOW_TAR_FALLBACK=1   allow tar instead of `git archive` when this is not a git repo (never ships .env)
#   KEEP_RELEASES          default 5
#
# Safety: only `docker compose -p cardiopcg`; no global prune/restart; nginx is NOT touched here (see install-vhost.sh);
# a single deploy at a time (flock on the server); automatic rollback if health checks fail.
set -euo pipefail

: "${DEPLOY_HOST:?set DEPLOY_HOST=user@host}"
DEPLOY_ROOT="${DEPLOY_ROOT:-/opt/cardiopcg}"
KEEP_RELEASES="${KEEP_RELEASES:-5}"
COMPOSE_REL="deploy/docker-compose.prod.yml"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"

SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=yes -o PasswordAuthentication=no -o ConnectTimeout=15)
[ -n "${DEPLOY_SSH_KEY:-}" ] && SSH_OPTS+=(-i "$DEPLOY_SSH_KEY" -o IdentitiesOnly=yes)
[ -n "${DEPLOY_KNOWN_HOSTS:-}" ] && SSH_OPTS+=(-o UserKnownHostsFile="$DEPLOY_KNOWN_HOSTS")
rssh() { ssh "${SSH_OPTS[@]}" "$DEPLOY_HOST" "$@"; }
log() { printf '[deploy %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

# remote step shared by deploy and rollback: wait until containers are healthy, then probe the local ports
REMOTE_HEALTH='
wait_healthy() {
  local c="$1" i st
  for i in $(seq 1 60); do
    st=$(docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}" "$c" 2>/dev/null || echo missing)
    [ "$st" = healthy ] || [ "$st" = running ] && { echo "$c: $st"; return 0; }
    sleep 5
  done
  echo "$c: NOT healthy (last: $st)"; return 1
}
api_port=$(grep -E "^CARDIOPCG_API_PORT=" "$ENVFILE" | cut -d= -f2); api_port=${api_port:-18400}
web_port=$(grep -E "^CARDIOPCG_WEB_PORT=" "$ENVFILE" | cut -d= -f2); web_port=${web_port:-18401}
wait_healthy cardiopcg-api && wait_healthy cardiopcg-frontend && wait_healthy cardiopcg-worker || exit 1
curl -fsS --max-time 10 "http://127.0.0.1:${api_port}/api/v1/system/health" >/dev/null || { echo "api health probe failed"; exit 1; }
curl -fsS --max-time 10 "http://127.0.0.1:${web_port}/healthz" >/dev/null || { echo "web health probe failed"; exit 1; }
echo "local health probes OK"
'

check_others() { # $1 = save|compare
  [ -z "${OTHER_SITES:-}" ] && return 0
  # shellcheck disable=SC2086
  "$HERE/post-deploy-check.sh" "--$1" "${TMPDIR:-/tmp}/cardiopcg-others.txt" $OTHER_SITES
}

# --------------------------------------------------------------------------------------------- rollback
if [ "${1:-}" = "--rollback" ]; then
  TARGET="${2:-}"
  log "ROLLBACK on $DEPLOY_HOST (target: ${TARGET:-previous release})"
  rssh "DEPLOY_ROOT='$DEPLOY_ROOT' TARGET='$TARGET' bash -s" <<'REMOTE'
set -euo pipefail
cd "$DEPLOY_ROOT"
cur=$(basename "$(readlink -f current)")
if [ -z "$TARGET" ]; then
  TARGET=$(ls -1t releases | grep -vx "$cur" | head -1 || true)
fi
[ -n "$TARGET" ] && [ -d "releases/$TARGET" ] || { echo "no rollback target found"; exit 1; }
echo "current=$cur -> rolling back to $TARGET"
cd "releases/$TARGET"
ENVFILE="$DEPLOY_ROOT/shared/.env"
ln -sfn "$ENVFILE" deploy/.env
export APP_VERSION="$TARGET"
# --no-deps/--no-build: reuse the already built image cardiopcg/*:$TARGET; skip the migrate one-shot
# (the old image does not know newer migrations; the schema is expand/contract compatible by policy).
docker compose -p cardiopcg -f deploy/docker-compose.prod.yml up -d --no-deps --no-build api worker beat frontend
ln -sfn "$DEPLOY_ROOT/releases/$TARGET" "$DEPLOY_ROOT/current"
REMOTE
  rssh "ENVFILE='$DEPLOY_ROOT/shared/.env' bash -s" <<< "$REMOTE_HEALTH"
  log "rollback complete"
  exit 0
fi

# --------------------------------------------------------------------------------------------- deploy
cd "$REPO"
if git rev-parse --git-dir >/dev/null 2>&1; then
  SHA="$(git rev-parse --short HEAD)"
  git diff --quiet HEAD -- 2>/dev/null || log "WARNING: uncommitted changes are NOT deployed (git archive ships HEAD)"
  PACK=(git archive --format=tar HEAD)
else
  [ "${ALLOW_TAR_FALLBACK:-0}" = "1" ] || die "not a git repository (set ALLOW_TAR_FALLBACK=1 to ship a tar of the working tree)"
  SHA="manual-$(date +%Y%m%d%H%M%S)"
  PACK=(tar --exclude='.git' --exclude='node_modules' --exclude='.venv' --exclude='dist' --exclude='.env' --exclude='.env.*' \
        --exclude='**/__pycache__' --exclude='e2e/.auth' --exclude='e2e/.e2e.env' --exclude='*.pem' --exclude='*.key' -cf - .)
fi
log "release $SHA -> $DEPLOY_HOST:$DEPLOY_ROOT/releases/$SHA"

log "validating compose file locally (no secrets printed)"
if command -v docker >/dev/null 2>&1; then
  # compose requires deploy/.env (env_file); use a throw-away placeholder copy, never a real one
  if [ -e "$REPO/deploy/.env" ]; then die "deploy/.env exists locally - remove it (real secrets live only on the server)"; fi
  sed -e 's/<[^>]*>/placeholder/g' "$HERE/../.env.production.example" > "$REPO/deploy/.env"
  docker compose -p cardiopcg -f "$REPO/$COMPOSE_REL" config -q || { rm -f "$REPO/deploy/.env"; die "compose config invalid"; }
  rm -f "$REPO/deploy/.env"
fi

check_others save || die "other sites are not healthy BEFORE deploy - aborting"

rssh "mkdir -p '$DEPLOY_ROOT/releases/$SHA' '$DEPLOY_ROOT/shared' '$DEPLOY_ROOT/backups' '$DEPLOY_ROOT/scripts'"
"${PACK[@]}" | rssh "tar -x -C '$DEPLOY_ROOT/releases/$SHA'"

PREV="$(rssh "basename \"\$(readlink -f '$DEPLOY_ROOT/current' 2>/dev/null)\" 2>/dev/null || true")"
log "previous release: ${PREV:-none}"

set +e
rssh "DEPLOY_ROOT='$DEPLOY_ROOT' SHA='$SHA' PRE_BACKUP='${PRE_DEPLOY_BACKUP:-0}' bash -s" <<'REMOTE'
set -euo pipefail
exec 9>/tmp/cardiopcg-deploy.lock
flock -n 9 || { echo "another deploy is running"; exit 1; }
cd "$DEPLOY_ROOT/releases/$SHA"
ENVFILE="$DEPLOY_ROOT/shared/.env"
[ -f "$ENVFILE" ] || { echo "missing $ENVFILE - create it from deploy/.env.production.example first"; exit 1; }
[ "$(stat -c %a "$ENVFILE")" = "600" ] || { echo "$ENVFILE must be chmod 600"; exit 1; }
if grep -q '<[A-Z_]*>' "$ENVFILE"; then echo "$ENVFILE still has <PLACEHOLDER> values"; exit 1; fi
ln -sfn "$ENVFILE" deploy/.env
export APP_VERSION="$SHA" GIT_COMMIT="$SHA"
C="docker compose -p cardiopcg -f deploy/docker-compose.prod.yml"
$C config -q
cp -f deploy/scripts/*.sh "$DEPLOY_ROOT/scripts/" && chmod 750 "$DEPLOY_ROOT"/scripts/*.sh
if [ "$PRE_BACKUP" = "1" ]; then "$DEPLOY_ROOT/scripts/backup.sh"; fi
nice -n 19 $C build
# migrations run as the one-shot `migrate` service (api depends on it) while the OLD api keeps serving until recreated
$C up -d --remove-orphans
ln -sfn "$DEPLOY_ROOT/releases/$SHA" "$DEPLOY_ROOT/current"
REMOTE
rc=$?
if [ $rc -eq 0 ]; then
  rssh "ENVFILE='$DEPLOY_ROOT/shared/.env' bash -s" <<< "$REMOTE_HEALTH"; rc=$?
fi
set -e

if [ $rc -ne 0 ]; then
  log "deploy FAILED (rc=$rc) - collecting logs and rolling back"
  rssh "cd '$DEPLOY_ROOT/current' 2>/dev/null && docker compose -p cardiopcg -f deploy/docker-compose.prod.yml logs --tail=40 api worker migrate 2>&1 | sed -E 's/(PASSWORD|SECRET|KEY|TOKEN)=[^ ]+/\1=***/g'" || true
  if [ -n "$PREV" ] && [ "$PREV" != "." ]; then
    DEPLOY_HOST="$DEPLOY_HOST" DEPLOY_ROOT="$DEPLOY_ROOT" "$0" --rollback "$PREV" || log "ROLLBACK FAILED - manual intervention needed"
  else
    log "no previous release to roll back to"
  fi
  exit 1
fi

check_others compare || { log "WARNING: other sites changed after deploy - investigate immediately (consider --rollback)"; exit 2; }

log "pruning old releases (keeping $KEEP_RELEASES) and dangling cardiopcg images"
rssh "cd '$DEPLOY_ROOT/releases' && ls -1t | tail -n +$((KEEP_RELEASES + 1)) | xargs -r -I{} rm -rf -- '$DEPLOY_ROOT/releases/{}'; docker image prune -f --filter label=project=cardiopcg --filter dangling=true >/dev/null" || true

log "DONE: $SHA is live (local probes OK). Next: scripts/post-deploy-check.sh --own https://cardiopcgai.189.uz"
