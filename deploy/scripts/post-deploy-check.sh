#!/usr/bin/env bash
# HTTP checks around a deploy. Read-only (only sends GET/HEAD requests).
#
# Other sites on the shared server (pass their URLs as arguments - nothing is hard-coded):
#   post-deploy-check.sh --save    before.txt https://site-a.example https://site-b.example   # BEFORE the deploy
#   post-deploy-check.sh --compare before.txt https://site-a.example https://site-b.example   # AFTER the deploy
#       exit 1 if any site that answered before now answers differently (code class change / timeout / 5xx)
# Our own site (smoke + headers):
#   post-deploy-check.sh --own https://cardiopcgai.189.uz
#
# Env: CHECK_TIMEOUT (default 15 s), CHECK_RETRIES (default 2).
set -uo pipefail

TIMEOUT="${CHECK_TIMEOUT:-15}"
RETRIES="${CHECK_RETRIES:-2}"
fail=0

code_of() { # url -> http code (000 on failure)
  local url="$1" c i
  for i in $(seq 0 "$RETRIES"); do
    c="$(curl -s -o /dev/null -w '%{http_code}' --max-time "$TIMEOUT" -L --max-redirs 3 -A 'cardiopcg-post-deploy-check/1.0' "$url" 2>/dev/null || true)"
    [ -n "$c" ] && [ "$c" != "000" ] && { echo "$c"; return; }
    sleep 1
  done
  echo "000"
}
class_of() { echo "${1:0:1}xx"; }

mode="${1:-}"
case "$mode" in
  --save)
    file="${2:?usage: --save FILE URL...}"; shift 2
    [ $# -gt 0 ] || { echo "no URLs given"; exit 0; }
    : > "$file"
    for u in "$@"; do
      c="$(code_of "$u")"
      printf '%s %s\n' "$u" "$c" | tee -a "$file"
      case "$c" in 5*|000) echo "  note: $u is already unhealthy before the deploy" ;; esac
    done
    ;;
  --compare)
    file="${2:?usage: --compare FILE URL...}"; shift 2
    [ -f "$file" ] || { echo "baseline $file not found"; exit 1; }
    for u in "$@"; do
      before="$(awk -v u="$u" '$1==u{print $2}' "$file" | head -1)"
      after="$(code_of "$u")"
      if [ -z "$before" ]; then echo "SKIP  $u (no baseline)"; continue; fi
      if [ "$before" = "000" ] || [ "${before:0:1}" = "5" ]; then
        echo "KEEP  $u was $before before, now $after (was already unhealthy)"; continue
      fi
      if [ "$(class_of "$before")" = "$(class_of "$after")" ]; then
        echo "OK    $u $before -> $after"
      else
        echo "FAIL  $u $before -> $after"; fail=1
      fi
    done
    ;;
  --own)
    base="${2:?usage: --own https://host}"; base="${base%/}"
    expect() { # name url expected_code
      local c; c="$(code_of "$2")"
      if [ "$c" = "$3" ]; then echo "OK    $1 ($c)"; else echo "FAIL  $1 expected $3 got $c"; fail=1; fi
    }
    expect "SPA index"          "$base/"                                200
    expect "API health"         "$base/api/v1/system/health"            200
    expect "API version"        "$base/api/v1/system/version"           200
    expect "docs hidden"        "$base/docs"                            404
    expect "openapi hidden"     "$base/openapi.json"                    404
    expect "auth required"      "$base/api/v1/auth/me"                  401
    hdr="$(curl -sI --max-time "$TIMEOUT" "$base/" || true)"
    for h in strict-transport-security x-content-type-options x-frame-options content-security-policy referrer-policy; do
      if printf '%s' "$hdr" | grep -qi "^$h:"; then echo "OK    header $h"; else echo "FAIL  header $h missing"; fail=1; fi
    done
    ;;
  *)
    sed -n '2,12p' "$0"; exit 64 ;;
esac

[ "$fail" -eq 0 ] && echo "RESULT: OK" || echo "RESULT: FAILED"
exit "$fail"
