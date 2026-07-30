# Rubric Checklist — Done / Incomplete / Not Done

Status legend: **Done** (built & self-checkable) · **Incomplete** (built,
awaiting homelab runner / live deploy to verify) · **Not Done**.

Anything marked Incomplete is code-complete in this repo; it flips to Done once
executed on the self-hosted runner against the live instance.

## Stage 0 — Repo structure
- [x] **Done** — skeleton, `.github/workflows/`, `security/`, `docker/`,
  `ansible/`, `docs/`, `evidence/` all present; `.gitignore` excludes secrets.

## Stage 1 — Self-hosted runner
- [ ] **Incomplete** — runner registration is a homelab action (see
  `docs/runner-setup.md`). All workflows target `runs-on: self-hosted`.

## Stage 2 — SAST + SCA (`ci.yml`)
- [x] **Done** — Semgrep (custom blocking rules + report-only packs),
  ESLint-security, OWASP Dependency-Check jobs written; thresholds documented.
- [ ] **Incomplete** — "fails on reintroduced high-severity issue" demo: run on
  the runner and confirm a deliberate regression reddens the build.

## Stage 3 — Automated security test cases (`security-tests.yml`)
- [x] **Done** — 11 test modules / 28 cases covering all 9 table rows + OAuth
  key perms; junit artifact; edge tests gate now, auth tests skip until seeded.
- [ ] **Incomplete** — wire auth secrets (`ADMIN_API_TOKEN`, `CUSTOMER_COOKIE`,
  `REMEMBER_COOKIE`, …) so the app-layer tests activate.

## Stage 4 — Developer notification
- [x] **Done** — Discord webhook + GitHub Issue on failure in `ci.yml`,
  `deploy.yml`, `security-tests.yml`.
- [ ] **Incomplete** — set `DISCORD_WEBHOOK_URL` secret; trigger a failure to
  confirm both fire.

## Stage 5 — Hardened image + secure deployment (`deploy.yml`)
- [x] **Done** — multi-stage `Dockerfile.paymenter` (non-root, pinned bases, no
  baked secrets, HEALTHCHECK); `docker-compose.yml` (frontend/app/db networks,
  reverse proxy TLS + headers + 4 virtual patches); build→Trivy→deploy wired.
- [ ] **Incomplete** — first real build/deploy on the runner (Docker daemon was
  offline on the dev machine; compose config validated, image build deferred).

## Stage 6 — Ansible + post-deploy validation
- [x] **Done** — playbooks (nftables + DOCKER-USER firewall, sysctls, secrets,
  certs); ZAP baseline + Nikto + `config-audit.sh` jobs.
- [ ] **Incomplete** — run playbooks against the host; confirm a reverted
  hardening step (e.g. `APP_DEBUG=true`) fails `config-audit.sh`.

## Stage 7 — Bug disclosure & developer engagement
- [ ] **Incomplete** — process track. `evidence/developer-engagement/` staged;
  ongoing maintainer outreach + individual bug reports (parallel work).

## Stage 8 — Docs
- [x] **Done** — `test-justification.md`, `maintenance-guide.md`, this
  checklist, `runner-setup.md`, top-level `README.md`.
- [ ] **Incomplete** — final Springer report shell (separate deliverable).
