#!/usr/bin/env bash
# Post-deploy configuration audit (Stage 6). Asserts that the hardening applied
# at deploy time still holds on the running stack. Exits non-zero if any check
# fails, so a reverted hardening step (e.g. re-enabled debug) fails the pipeline.
#
# Env:
#   BASE_URL            default https://paymenter.homelab.local
#   COMPOSE_FILE        default docker/docker-compose.yml
#   PAYMENTER_CONTAINER override container discovery
set -u

BASE_URL="${BASE_URL:-https://paymenter.homelab.local}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/docker-compose.yml}"
HOST="${BASE_URL#*://}"
FAILS=0

pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAILS=$((FAILS+1)); }

container() {
  if [ -n "${PAYMENTER_CONTAINER:-}" ]; then echo "$PAYMENTER_CONTAINER"; return; fi
  docker compose -f "$COMPOSE_FILE" ps -q paymenter 2>/dev/null
}
C="$(container)"

echo "== 1. HTTP -> HTTPS redirect =="
code="$(curl -s -o /dev/null -w '%{http_code}' -I "http://${HOST}/" --max-time 15)"
case "$code" in
  301|308) pass "http returns $code redirect" ;;
  *) fail "http returned $code (expected 301/308)" ;;
esac

echo "== 2. Security headers present over HTTPS =="
hdrs="$(curl -sk -D - -o /dev/null "https://${HOST}/" --max-time 15)"
for h in "Strict-Transport-Security" "X-Content-Type-Options" "X-Frame-Options"; do
  echo "$hdrs" | grep -qi "^${h}:" && pass "$h present" || fail "$h missing"
done

echo "== 3. CORS not wildcard =="
acao="$(curl -sk -H 'Origin: https://evil.example' -D - -o /dev/null "https://${HOST}/api/soap/?wsdl=1" --max-time 15 | grep -i '^access-control-allow-origin:' | tr -d '\r')"
if echo "$acao" | grep -q '\*'; then fail "ACAO wildcard present ($acao)"; else pass "ACAO not wildcard"; fi

if [ -z "$C" ]; then
  fail "paymenter container not found — skipping container-level checks"
else
  echo "== 4. Debug mode disabled =="
  dbg="$(docker exec "$C" printenv APP_DEBUG 2>/dev/null)"
  [ "$dbg" = "false" ] && pass "APP_DEBUG=false" || fail "APP_DEBUG='$dbg' (expected false)"

  echo "== 5. Container not running request handlers as root =="
  # nginx worker + php-fpm pool must be the unprivileged nginx user.
  workers="$(docker exec "$C" ps -o user,comm 2>/dev/null | grep -E 'nginx: worker|php-fpm: pool' || true)"
  if [ -n "$workers" ]; then
    if echo "$workers" | grep -qE '^root '; then fail "a worker runs as root:\n$workers"; else pass "workers run non-root"; fi
  else
    cfg_user="$(docker inspect -f '{{.Config.User}}' "$C" 2>/dev/null)"
    [ "$cfg_user" = "nginx" ] && pass "container User=nginx" || fail "container User='$cfg_user'"
  fi

  echo "== 6. OAuth private key permissions <= 660 =="
  mode="$(docker exec "$C" stat -c '%a' /app/storage/oauth-private.key 2>/dev/null)"
  if [ -z "$mode" ]; then
    echo "  [SKIP] oauth-private.key not generated yet"
  else
    case "$mode" in 600|640|660) pass "key mode $mode" ;; *) fail "key mode $mode (expected <=660)" ;; esac
  fi
fi

echo "== 7. Host secret files are 600 =="
for f in docker/secrets/app_key docker/secrets/db_password docker/secrets/db_root_password; do
  if [ -f "$f" ]; then
    m="$(stat -c '%a' "$f" 2>/dev/null || stat -f '%Lp' "$f" 2>/dev/null)"
    [ "$m" = "600" ] && pass "$f is 600" || fail "$f is $m (expected 600)"
  fi
done

echo
if [ "$FAILS" -gt 0 ]; then
  echo "config-audit: $FAILS check(s) FAILED"
  exit 1
fi
echo "config-audit: all checks passed"
