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
- `CUSTOMER_COOKIE`, `UPGRADE_SERVICE_ID`, `CHECKOUT_PRODUCT_ID`,
  `RACE_COUPON_CODE` deliberately **not** wired: the 5 tests that consume
  them (`test_mass_assignment.py`, `test_config_injection.py`,
  `test_coupon_race_condition.py`) `POST` to URLs assuming classic
  server-rendered forms (`/checkout/{id}`, `/services/{id}/upgrade`,
  `/cart`), but those flows are actually Livewire components — `GET`-only
  routes (checkout is also at a different nested path entirely). Wiring
  these secrets would make the tests **pass without ever exercising what
  they claim to check** (a 404 from the wrong URL happens to satisfy their
  current assertions) — worse than the honest skip. Rewriting them to speak
  Livewire's real update-request protocol is tracked as separate follow-up
  work, not done this session.
- `LOWPRIV_API_TOKEN`/`LOWPRIV_ROLE_ID` also not wired: confirmed live
  (`404`, `"route api/v1/admin/roles/1 could not be found"`) that
  `test_rbac_wildcard.py` targets an API resource that was never registered
  in `routes/api.php` at all — no route exists to test against.

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
