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
- [ ] **Incomplete** — first real run on the runner happened in Phase 1 (found
  `pip` missing on the Runner, fixed); get a clean confirmed pass and actually
  read the ZAP/Nikto/config-audit results before calling this Done. Auth
  secrets (`ADMIN_API_TOKEN`, `CUSTOMER_COOKIE`, `REMEMBER_COOKIE`, …) still
  not wired, so app-layer tests still skip.

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
- [ ] **Incomplete** — confirm a reverted hardening step (e.g.
  `APP_DEBUG=true`) actually fails `config-audit.sh` (config-audit ran as part
  of the first `security-tests.yml` execution, but this specific negative-test
  scenario hasn't been deliberately exercised).

## Stage 7 — Bug disclosure & developer engagement
- [ ] **Incomplete** — process track. `evidence/developer-engagement/` staged;
  ongoing maintainer outreach + individual bug reports (parallel work).

## Stage 8 — Docs
- [x] **Done** — `test-justification.md`, `maintenance-guide.md`, this
  checklist, `runner-setup.md`, top-level `README.md`.
- [ ] **Incomplete** — final Springer report shell (separate deliverable).
