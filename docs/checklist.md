# Rubric Checklist — Done / Incomplete / Not Done

Status legend: **Done** (built & self-checkable) · **Incomplete** (built,
awaiting homelab runner / live deploy to verify) · **Not Done**.

Anything marked Incomplete is code-complete in this repo; it flips to Done once
executed on the self-hosted runner against the live instance.

## Stage 0 — Repo structure
- [x] **Done** — skeleton, `.github/workflows/`, `security/`, `docker/`,
  `ansible/`, `docs/`, `evidence/` all present; `.gitignore` excludes secrets.

## Stage 1 — Self-hosted runner
- [x] **Done** — registered as a systemd service on the Runner VM
  (`actions.runner.HaidenVeno-Paymenter-CICD.CICD-Runner-hveno`, survives
  reboot). All workflows target `runs-on: self-hosted`.

## Stage 2 — SAST, Secrets, IaC & SCA (`ci.yml`)
- [x] **Done** — Semgrep (custom rules + `p/default`/`p/owasp-top-ten` ERROR gate
  + report-only packs), ESLint-security, **Gitleaks** (secrets), **Hadolint**
  (Dockerfile), **Trivy config** (IaC), OWASP Dependency-Check. All gates
  calibrated against the real app; thresholds documented.
- [x] **Done (locally proven)** — detection verified: custom rules fire on the
  vulnerable code; a planted OS-command-injection/`eval` is caught by `p/default`
  and ESLint (build-failing); Gitleaks caught planted tokens.
- [x] **Done** — full run on the self-hosted runner (Actions UI): all 6 jobs
  green (semgrep, eslint-security, gitleaks, hadolint, trivy-config,
  dependency-check). Along the way, fixed real bugs the first execution
  surfaced (semgrep/eslint/trivy-action pin, gitleaks false-positive
  allowlist, dependency-check CVEs) — see `CLAUDE.md`'s Phase 1 gotchas.

## Stage 3 — Automated security test cases (`security-tests.yml`)
- [x] **Done** — 11 test modules / 28 cases covering all 9 table rows + OAuth
  key perms; junit artifact; edge tests gate now, auth tests skip until seeded.
- [x] **Done** — clean confirmed run on the runner: `post-deploy-nikto` and
  `post-deploy-config-audit` all green. `post-deploy-zap`'s one real finding
  ("Content-Security-Policy Header Not Set") is fixed — see Stage 5/6 below
  and `docs/allowlist.md`.
- [x] **Done** — auth secrets wired for real (`ADMIN_API_TOKEN`,
  `REMEMBER_COOKIE`, `EXPIRED_COOKIE`), against real users/tokens/sessions
  created on Staging, not placeholders. `regression-tests` now: **15 passed,
  1 failed (a real finding, not a bug — see below), 12 skipped (all
  documented, not blocking)**. Also fixed a real bug in the test harness
  itself while wiring this: `conftest.py`'s `http` fixture tried to disable
  redirect-following via `s.request = _req`, but `Session.get()`/`.post()`
  inject `allow_redirects=True` into kwargs *before* calling `.request()`,
  so the override silently never took effect for `.get()`/`.post()` calls —
  fixed by overriding those methods directly.
- **Real finding, currently unpatched**: `test_remember_mfa_bypass.py` fails
  — presenting *only* a `paymenter_remember` cookie (no session, no
  password, no 2FA) against `/admin` returns the actual Filament Dashboard
  with `HTTP 200`, not the expected redirect. This is exactly the MFA-bypass
  class the test was written to catch (Lab 5 s3.8) — confirmed live via
  both `curl` and pytest, not a test-infra artifact. See `docs/allowlist.md`.
- **Follow-up session — the 5 tests above are now genuinely rewritten and
  running**, not skipped. `security/tests/livewire_helpers.py` drives
  Checkout/Upgrade/Cart's real AJAX protocol (`POST {base}/paymenter/update`
  with a `wire:snapshot` pulled from the page, matching how the actual
  frontend talks to these components) instead of the guessed classic-form
  URLs that used to 404 their way to a false pass. `security/tests/
  remote_helpers.py` adds SSH-based ground-truth DB/container verification
  against the deploy target (the admin API doesn't expose enough detail for
  some of these, e.g. per-service config rows) — also used to fix
  `test_oauth_key_perms.py`'s own bug (it shelled out to a *local* `docker`,
  which silently never found anything in CI since the Runner and Staging
  are different hosts). Full local suite run: **23 passed, 2 failed (both
  real, newly-confirmed findings — see below), 1 xfail (coupon race,
  disclosed/accepted risk), 2 skipped** (`REMEMBER_COOKIE`/`EXPIRED_COOKIE`
  — separate secrets, unrelated to this rewrite).
- **New real finding #1 — RBAC self-escalation, currently unpatched**:
  `test_rbac_wildcard.py` (rewritten against the real mechanism — see
  `docs/allowlist.md`) fails. A "viewer" staff account holding only
  `admin.roles.viewAny`/`admin.roles.view` can grant **itself** wildcard
  (`*`, full-admin) permissions by editing its own role through the
  Filament panel. Live-verified end-to-end (then reverted): the write lands
  in the `roles` table. `RoleResource::canEdit()` is hardcoded to
  `$record->id !== 1` and never consults `RolePolicy::update()`; `Role.php`
  has no save-time guard against `'*'`. This contradicts what the test
  previously assumed was already fixed (Lab 4 s1.2/10.2, Lab 5 s3.5-s3.6) —
  that fix either regressed or was never applied to this fork.
- **New real finding #2 — OAuth client secrets still plaintext**:
  `test_oauth_key_perms.py::test_oauth_client_secrets_not_plaintext` fails.
  All three OAuth client-secret settings (`oauth_google_client_secret`,
  `oauth_github_client_secret`, `oauth_discord_client_secret`) are still
  declared `'type' => 'text'` in `app/Classes/Settings.php` — the claimed
  s3.4 fix (`'type' => 'password', 'encrypted' => true`) isn't present in
  this fork. The key-permissions half of this test file passes
  (`oauth-private.key` is `600`) — but note it has to be regenerated after
  every container recreate (`php artisan passport:keys`); the keys live
  outside every named volume, a known unfixed gap (see `docs/allowlist.md`).
- Both new findings are left as hard (non-xfail) gates, same treatment as
  the MFA bypass — real regressions, not accepted/disclosed risk.

## Stage 4 — Developer notification
- [x] **Done** — Discord webhook + GitHub Issue on failure in `ci.yml`,
  `deploy.yml`, `security-tests.yml`.
- [ ] **Incomplete** — set `DISCORD_WEBHOOK_URL` secret; trigger a failure to
  confirm both fire.

## Stage 5 — Hardened image + secure deployment (`deploy.yml`)
- [x] **Done** — multi-stage `Dockerfile.paymenter` (non-root, pinned +
  digest-locked bases, no baked secrets, HEALTHCHECK); `docker-compose.yml`
  (frontend/app/db networks, reverse proxy TLS + headers + 4 virtual patches);
  build→Trivy→deploy wired and refactored to actually deploy to **Staging over
  SSH** (previously assumed runner == deploy target).
- [x] **Done** — first real build/deploy on the runner, against Staging:
  `build` → `trivy-scan` → `deploy` all green via GitHub Actions, app
  container healthy, `https://paymenter.homelab.local/` returns `200`. Also
  cleared a CRITICAL OpenSSL CVE (CVE-2026-31789) found by the first real
  Trivy scan.

## Stage 6 — Ansible + post-deploy validation
- [x] **Done** — playbooks (nftables + DOCKER-USER firewall, sysctls, secrets,
  certs); ZAP baseline + Nikto + `config-audit.sh` jobs. Also added
  `provision.yml`/`docker.yml` to capture base VM bootstrap (user, persistent
  mgmt netplan, sshd, Docker install) that was previously done by hand.
- [x] **Done** — playbooks run for real against Staging (`site.yml`:
  provision→docker→secrets→certs→harden), including the nftables/DOCKER-USER
  firewall reload — confirmed no SSH lockout, confirmed idempotent on repeat
  runs.
- [x] **Done** — ZAP's one real finding (missing CSP header, `10038`) fixed in
  `docker/reverse-proxy/conf.d/security-headers.conf` and validated via a
  direct manual ZAP re-scan (`FAIL-NEW: 0`). Policy trade-offs (`unsafe-inline`/
  `unsafe-eval` needed for Filament/Livewire/Alpine.js) documented in
  `docs/allowlist.md`. Remaining WARN-level findings tracked there, not gated.
- [ ] **Incomplete** — confirm a reverted hardening step (e.g.
  `APP_DEBUG=true`) actually fails `config-audit.sh` (config-audit ran as part
  of the first `security-tests.yml` execution, but this specific negative-test
  scenario hasn't been deliberately exercised).

## Stage 7 — Bug disclosure & developer engagement
- [ ] **Incomplete** — process track. `evidence/developer-engagement/` staged;
  ongoing maintainer outreach + individual bug reports (parallel work).

## Stage 8 — Docs
- [x] **Done** — `test-justification.md`, `maintenance-guide.md`, this
  checklist, `runner-setup.md`, `allowlist.md` (every scan
  exception/threshold and its rationale, cataloged in one place), top-level
  `README.md`.
- [ ] **Incomplete** — final Springer report shell (separate deliverable).
