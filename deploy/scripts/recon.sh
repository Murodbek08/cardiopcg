#!/usr/bin/env bash
# CardioPCG AI - Step 0 server RECON. STRICTLY READ-ONLY.
#
# Runs ON the server (it only writes its own report files into ~/cardiopcg-recon/). Run it over SSH from your machine:
#   ssh deploy@<server> 'bash -s' < deploy/scripts/recon.sh
# Never changes: containers, nginx, ufw, cron, packages, files outside ~/cardiopcg-recon. No restart/reload/rm/prune.
# Privileged reads use `sudo -n` (non-interactive); if sudo is not available the section notes it and continues.
set -uo pipefail

OUT="${RECON_DIR:-$HOME/cardiopcg-recon}"
STAMP="$(date +%F-%H%M)"
PORT_FROM="${PORT_FROM:-18400}"
PORT_TO="${PORT_TO:-18409}"
DOMAIN="${DOMAIN:-cardiopcgai.189.uz}"
mkdir -p "$OUT"
REPORT="$OUT/RECON-$STAMP.txt"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  if sudo -n true 2>/dev/null; then SUDO="sudo -n"; else SUDO="__nosudo__"; fi
fi
priv() { # run a privileged READ-ONLY command
  if [ "$SUDO" = "__nosudo__" ]; then echo "(skipped: needs passwordless sudo) $*"; return 0; fi
  $SUDO "$@"
}
section() { printf '\n==================== %s ====================\n' "$1"; }
run() { printf '\n$ %s\n' "$*"; "$@" 2>&1 || echo "(exit $?)"; }

{
  echo "CardioPCG recon $STAMP on $(hostname) - READ-ONLY"

  section "1. System resources"
  run uname -a
  run bash -c 'lsb_release -a 2>/dev/null || cat /etc/os-release'
  run nproc
  run free -h
  run df -hT
  run df -ih
  run uptime
  run vmstat 1 3
  if command -v docker >/dev/null; then run docker system df; fi

  section "2. Containers / compose projects / networks / volumes"
  if command -v docker >/dev/null; then
    run docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
    run docker compose ls -a
    run docker network ls
    run docker volume ls
    run docker stats --no-stream
  else
    echo "docker not found"
  fi

  section "3. Listening ports"
  priv ss -ltnp 2>&1
  ss -ltn | awk 'NR>1{print $4}' | sed 's/.*://' | sort -n | uniq > "$OUT/used-ports.txt"
  echo "--- chosen range ${PORT_FROM}-${PORT_TO}: conflicts below (none = free)"
  busy=0
  for p in $(seq "$PORT_FROM" "$PORT_TO"); do
    if grep -qx "$p" "$OUT/used-ports.txt"; then echo "BUSY: $p"; busy=1; fi
  done
  [ "$busy" -eq 0 ] && echo "range ${PORT_FROM}-${PORT_TO} is FREE"
  echo "--- compose project name 'cardiopcg' already present?"
  (docker compose ls -a 2>/dev/null | grep -w cardiopcg) || echo "no 'cardiopcg' project yet (good)"

  section "4. nginx"
  run bash -c 'nginx -v 2>&1'
  priv nginx -T > "$OUT/nginx-full-dump-$STAMP.txt" 2>&1
  echo "(full nginx -T dump saved to $OUT/nginx-full-dump-$STAMP.txt - contains server config, keep private)"
  run ls -la /etc/nginx/sites-enabled/ /etc/nginx/conf.d/
  run bash -c 'grep -R "server_name" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/ 2>/dev/null'
  run bash -c 'grep -R "cardiopcgai" /etc/nginx/ 2>/dev/null || echo "cardiopcgai: not configured yet"'
  run bash -c 'grep -R "set_real_ip_from\|real_ip_header" /etc/nginx/ 2>/dev/null | head -20 || true'

  section "5. certbot / certificates"
  priv certbot certificates 2>&1
  run bash -c 'systemctl list-timers 2>/dev/null | grep -i certbot || echo "no certbot timer"'

  section "6. Security posture"
  priv ufw status verbose 2>&1
  run bash -c 'systemctl status fail2ban --no-pager 2>&1 | head -15'
  run bash -c 'ss -ltn | grep -E ":(22|80|443)\s" || true'
  run bash -c 'grep -E "^(PasswordAuthentication|PermitRootLogin)" /etc/ssh/sshd_config 2>/dev/null || true'

  section "7. Other projects and cron (read-only listing)"
  run bash -c 'ls -la /opt /srv 2>/dev/null | head -60'
  run bash -c 'ls -la /home/*/ 2>/dev/null | head -60'
  run bash -c 'crontab -l 2>&1 || true'
  priv ls /etc/cron.d/ 2>&1
  run bash -c "dig +short $DOMAIN 2>/dev/null || getent hosts $DOMAIN || echo 'no dig/getent result'"

  section "8. Tools needed by deploy / backup"
  for t in docker age rclone curl openssl flock tar git; do
    printf '%-8s ' "$t"; (command -v "$t" || echo "MISSING")
  done
  run bash -c 'docker compose version 2>&1'

  section "9. Decision helper (fill in by hand)"
  avail_gb="$(free -g | awk '/^Mem:/{print $7}')"
  disk_use="$(df --output=pcent / | tail -1 | tr -dc '0-9')"
  echo "available RAM (GB): ${avail_gb:-?}   (need >= 3, else lower limits / Celery concurrency 1)"
  echo "root disk used (%): ${disk_use:-?}   (need >= 20 GB free and < 80% used)"
  [ -n "${avail_gb:-}" ] && [ "${avail_gb:-0}" -lt 3 ] && echo "WARNING: low RAM - adjust limits before deploying"
  [ -n "${disk_use:-}" ] && [ "${disk_use:-0}" -ge 80 ] && echo "WARNING: disk >= 80% - STOP and ask the owner"
  echo "If anything above is unexpected (port clash, nginx -T error, low RAM/disk) - STOP and report; do not deploy."
} 2>&1 | tee "$REPORT"

chmod 600 "$REPORT" "$OUT"/*.txt 2>/dev/null || true
echo
echo "Report: $REPORT   (read-only run complete; nothing on the server was changed)"
