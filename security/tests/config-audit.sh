#!/usr/bin/env bash
# Post-deploy configuration audit (Stage 6). Asserts that the hardening applied
# at deploy time still holds on the running stack. Exits non-zero if any check
# fails, so a reverted hardening step (e.g. re-enabled debug) fails the pipeline.
#
# Container- and secrets-level checks run against the actual deploy target
# (Staging/Prod) over SSH, not locally — the runner this script executes on is
# NOT the deploy target since deploy.yml's Phase 1 refactor (found this the
# hard way: this script pre-dated that refactor and was never updated, so it
# always reported "paymenter container not found" here).
#
# Env:
#   BASE_URL            default https://paymenter.homelab.local
#   DEPLOY_HOST/USER/SSH_KEY/PATH  same convention + defaults as deploy.yml
#   PAYMENTER_CONTAINER override container discovery
set -u

BASE_URL="${BASE_URL:-https://paymenter.homelab.local}"
HOST="${BASE_URL#*://}"
FAILS=0

DEPLOY_HOST="${DEPLOY_HOST:-10.0.20.20}"
DEPLOY_USER="${DEPLOY_USER:-hveno}"
DEPLOY_SSH_KEY="${DEPLOY_SSH_KEY:-/home/hveno/.ssh/id_ed25519_deploy}"
DEPLOY_PATH="${DEPLOY_PATH:-/home/hveno/Paymenter-CICD/docker}"

pass() { echo "  [PASS] $1"; }
fail() { echo "  [FAIL] $1"; FAILS=$((FAILS+1)); }

remote() {
  ssh -o StrictHostKeyChecking=accept-new -i "$DEPLOY_SSH_KEY" "$DEPLOY_USER@$DEPLOY_HOST" "$@"
}

container() {
  if [ -n "${PAYMENTER_CONTAINER:-}" ]; then echo "$PAYMENTER_CONTAINER"; return; fi
  remote "docker compose -f '$DEPLOY_PATH/docker-compose.yml' ps -q paymenter" 2>/dev/null
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
  fail "paymenter container not found on $DEPLOY_HOST — skipping container-level checks"
else
  echo "== 4. Debug mode disabled =="
  dbg="$(remote "docker exec '$C' printenv APP_DEBUG" 2>/dev/null)"
  [ "$dbg" = "false" ] && pass "APP_DEBUG=false" || fail "APP_DEBUG='$dbg' (expected false)"

  echo "== 5. Container not running request handlers as root =="
  # nginx worker + php-fpm pool must be the unprivileged nginx user.
  workers="$(remote "docker exec '$C' ps -o user,comm" 2>/dev/null | grep -E 'nginx: worker|php-fpm: pool' || true)"
  if [ -n "$workers" ]; then
    if echo "$workers" | grep -qE '^root '; then fail "a worker runs as root:\n$workers"; else pass "workers run non-root"; fi
  else
    cfg_user="$(remote "docker inspect -f '{{.Config.User}}' '$C'" 2>/dev/null)"
    [ "$cfg_user" = "nginx" ] && pass "container User=nginx" || fail "container User='$cfg_user'"
  fi

  echo "== 6. OAuth private key permissions <= 660 =="
  mode="$(remote "docker exec '$C' stat -c '%a' /app/storage/oauth-private.key" 2>/dev/null)"
  if [ -z "$mode" ]; then
    echo "  [SKIP] oauth-private.key not generated yet"
  else
    case "$mode" in 600|640|660) pass "key mode $mode" ;; *) fail "key mode $mode (expected <=660)" ;; esac
  fi
fi

echo "== 7. Deploy-target secret files are owner-only (400, container-readable) =="
# 400, not 600: secrets.yml owns these to the app container's runtime uid
# (10000, pinned in docker/Dockerfile.paymenter) since standalone `docker
# compose` bind-mounts file-type secrets as-is, honoring host ownership.
for f in app_key db_password db_root_password; do
  m="$(remote "stat -c '%a' '$DEPLOY_PATH/secrets/$f'" 2>/dev/null)"
  [ "$m" = "400" ] && pass "secrets/$f is 400" || fail "secrets/$f is '$m' (expected 400)"
done

echo
if [ "$FAILS" -gt 0 ]; then
  echo "config-audit: $FAILS check(s) FAILED"
  exit 1
fi
echo "config-audit: all checks passed"
