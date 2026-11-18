#!/usr/bin/env bash
# OPTIONAL helper, run ON the server by a human after recon.sh: installs the ONE new nginx vhost safely.
# Backup /etc/nginx -> install 3 files -> enable -> `nginx -t` -> reload (never restart). On any error the vhost is
# disabled again and nothing else is touched. Other sites and nginx.conf are never edited.
#
#   CERT_MODE=letsencrypt|origin  API_PORT=18400 WEB_PORT=18401  deploy/scripts/install-vhost.sh
#     letsencrypt -> /etc/letsencrypt/live/cardiopcgai.189.uz/{fullchain,privkey}.pem  (certbot must already have issued it)
#     origin      -> /etc/ssl/cardiopcg/origin.pem + origin.key (Cloudflare Origin Certificate, chmod 600 root)
set -euo pipefail

DOMAIN="cardiopcgai.189.uz"
API_PORT="${API_PORT:-18400}"
WEB_PORT="${WEB_PORT:-18401}"
CERT_MODE="${CERT_MODE:-origin}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../nginx" && pwd)"
SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"

case "$CERT_MODE" in
  letsencrypt) CERT="/etc/letsencrypt/live/$DOMAIN/fullchain.pem"; KEY="/etc/letsencrypt/live/$DOMAIN/privkey.pem" ;;
  origin)      CERT="/etc/ssl/cardiopcg/origin.pem";               KEY="/etc/ssl/cardiopcg/origin.key" ;;
  *) echo "CERT_MODE must be letsencrypt or origin" >&2; exit 1 ;;
esac
$SUDO test -f "$CERT" && $SUDO test -f "$KEY" || { echo "certificate files not found ($CERT)" >&2; exit 1; }
[ -d /etc/nginx/sites-available ] && [ -d /etc/nginx/sites-enabled ] || { echo "unexpected nginx layout" >&2; exit 1; }

echo "== 1/5 nginx -t BEFORE any change (must already pass)"
$SUDO nginx -t

BK="/root/backup-nginx-$(date +%F-%H%M)"
echo "== 2/5 backup /etc/nginx -> $BK"
$SUDO cp -a /etc/nginx "$BK"

echo "== 3/5 install files"
tmp="$(mktemp)"
sed -e "s#@API_PORT@#$API_PORT#g" -e "s#@WEB_PORT@#$WEB_PORT#g" -e "s#@CERT@#$CERT#g" -e "s#@CERT_KEY@#$KEY#g" \
    "$SRC/cardiopcgai.189.uz.conf.template" > "$tmp"
$SUDO install -m 644 "$tmp" "/etc/nginx/sites-available/$DOMAIN"; rm -f "$tmp"
$SUDO install -m 644 "$SRC/cardiopcg-cloudflare-realip.conf" /etc/nginx/cardiopcg-cloudflare-realip.conf
$SUDO install -m 644 "$SRC/cardiopcg-security-headers.conf" /etc/nginx/cardiopcg-security-headers.conf
$SUDO mkdir -p /var/www/certbot

echo "== 4/5 enable + test"
$SUDO ln -sfn "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
if ! $SUDO nginx -t; then
  echo "nginx -t FAILED: disabling the new vhost; NOT reloading" >&2
  $SUDO rm -f "/etc/nginx/sites-enabled/$DOMAIN"
  $SUDO nginx -t || true
  exit 1
fi

echo "== 5/5 reload (not restart)"
$SUDO systemctl reload nginx
echo "done. Check:  curl -sI https://$DOMAIN/ | head   and the OTHER sites (post-deploy-check.sh --compare ...)"
echo "Undo:        sudo rm /etc/nginx/sites-enabled/$DOMAIN && sudo nginx -t && sudo systemctl reload nginx   (backup: $BK)"
