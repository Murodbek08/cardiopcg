#!/usr/bin/env bash
# CardioPCG AI backup (runs ON the server as the `deploy` user; cron: 15 3 * * * ...).
# PostgreSQL (pg_dump -Fc) + MinIO volume + nginx vhost, each encrypted with `age` to a PUBLIC key
# (BACKUP_AGE_RECIPIENT). The private key is NOT on the server. Local retention + optional rclone offsite.
# Touches only cardiopcg containers/volumes and $BACKUP_DIR. Never prints secrets.
set -euo pipefail
umask 077

ROOT="${DEPLOY_ROOT:-/opt/cardiopcg}"
ENVFILE="${ENVFILE:-$ROOT/shared/.env}"
[ -f "$ENVFILE" ] || { echo "missing $ENVFILE" >&2; exit 1; }
envget() { grep -E "^$1=" "$ENVFILE" | tail -1 | cut -d= -f2- || true; }

PGUSER="$(envget POSTGRES_USER)"; PGDB="$(envget POSTGRES_DB)"
AGE_RECIPIENT="${BACKUP_AGE_RECIPIENT:-$(envget BACKUP_AGE_RECIPIENT)}"
DIR="${BACKUP_DIR:-$(envget BACKUP_DIR)}"; DIR="${DIR:-$ROOT/backups}"
RETENTION="${BACKUP_RETENTION_DAYS:-$(envget BACKUP_RETENTION_DAYS)}"; RETENTION="${RETENTION:-7}"
RCLONE_REMOTE="${BACKUP_RCLONE_REMOTE:-$(envget BACKUP_RCLONE_REMOTE)}"

case "$AGE_RECIPIENT" in age1*) ;; *) echo "BACKUP_AGE_RECIPIENT must be an age public key (age1...)" >&2; exit 1 ;; esac
command -v age >/dev/null || { echo "age is not installed" >&2; exit 1; }
docker inspect cardiopcg-postgres >/dev/null 2>&1 || { echo "container cardiopcg-postgres not found" >&2; exit 1; }

STAMP="$(date +%F-%H%M)"
mkdir -p "$DIR"
log() { printf '[backup %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

# 1) PostgreSQL (custom format -> parallel/selective restore possible)
log "postgres dump"
docker exec cardiopcg-postgres pg_dump -U "$PGUSER" -d "$PGDB" -Fc --no-owner \
  | age -r "$AGE_RECIPIENT" > "$DIR/pg-$STAMP.dump.age.tmp"
[ -s "$DIR/pg-$STAMP.dump.age.tmp" ] || { echo "empty pg dump" >&2; rm -f "$DIR/pg-$STAMP.dump.age.tmp"; exit 1; }
mv "$DIR/pg-$STAMP.dump.age.tmp" "$DIR/pg-$STAMP.dump.age"

# 2) MinIO data (read-only mount of OUR volume; stream-encrypted, no plaintext archive on disk)
log "storage volume"
docker run --rm -v cardiopcg_storage:/data:ro alpine:3.20 tar -czf - -C /data . \
  | age -r "$AGE_RECIPIENT" > "$DIR/storage-$STAMP.tgz.age.tmp"
mv "$DIR/storage-$STAMP.tgz.age.tmp" "$DIR/storage-$STAMP.tgz.age"

# 3) nginx vhost + snippets (small, only our own files)
log "nginx vhost"
if [ -f /etc/nginx/sites-available/cardiopcgai.189.uz ]; then
  tar -czf - -C /etc/nginx sites-available/cardiopcgai.189.uz cardiopcg-cloudflare-realip.conf cardiopcg-security-headers.conf 2>/dev/null \
    | age -r "$AGE_RECIPIENT" > "$DIR/nginx-$STAMP.tgz.age" || log "nginx files not readable (skipped)"
fi

# 4) deploy/.env (encrypted; contains all secrets -> only ever stored encrypted)
log "env file"
age -r "$AGE_RECIPIENT" -o "$DIR/env-$STAMP.age" "$ENVFILE"

# 5) offsite (already encrypted files only)
if [ -n "$RCLONE_REMOTE" ]; then
  if command -v rclone >/dev/null; then
    log "offsite -> $RCLONE_REMOTE"
    rclone copy "$DIR" "$RCLONE_REMOTE" --include "*-$STAMP.*age" --transfers 2
  else
    log "WARNING: BACKUP_RCLONE_REMOTE set but rclone is missing"
  fi
fi

# 6) local retention (only our files, only in $DIR)
find "$DIR" -maxdepth 1 -type f \( -name 'pg-*.age' -o -name 'storage-*.age' -o -name 'nginx-*.age' -o -name 'env-*.age' \) -mtime +"$RETENTION" -delete

log "done: $(ls -1 "$DIR"/*-"$STAMP".* | wc -l) files, $(du -sh "$DIR" | cut -f1) total in $DIR"
