# CLAUDE.md — project context & handoff

This repo is a **DevSecOps security pipeline for the Paymenter application**
(Seneca WAS705 final project, Group 8). It is designed to run on-premise: a
GitHub Actions **self-hosted runner** executes all jobs; GitHub is only the code
host + orchestration + Issues surface. Job execution, security tooling, and
deployment never leave the owner's infrastructure.

This file is the durable context for any Claude Code instance picking up the
work (e.g. running on the **Runner VM**). Read it, then `docs/network-topology.md`.

## Working preferences (important)
- **Do NOT add a `Co-Authored-By: Claude` trailer to commits.** The user does
  not want it. Omit it from every commit.
- Commit only when asked; branch off `main` first if asked to commit while on it.
- The user is a capable web-security student (Windows 11 host + VirtualBox
  homelab, comfortable with Docker/git/Actions/pentest tooling). Be concise and
  technical; explain *why*, not basics.

## The application (separate repo)
- Source: fork **`HaidenVeno/Paymenter`**, branch
  **`fix/upgrade-configoptions-injection`** (Laravel/PHP + Livewire + Filament).
- This pipeline repo does **not** vendor the app — `Dockerfile.paymenter` clones
  the fork at build time (`PAYMENTER_REPO` / `PAYMENTER_REF` build args, defaulted
  via the `APP_REPO`/`APP_REF` workflow env / repo variables).
- The pipeline repo lives on GitHub as **`HaidenVeno/Paymenter-CICD`** (push over
  HTTPS; Git Credential Manager supplies the HaidenVeno token. Note: the SSH key
  on the Windows host authenticates as a *different* account, `hveno_seneca`, so
  SSH pushes 404 — use HTTPS).

## Current state (2026-08)
**Built (all 10 stages scaffolded):** `ci.yml` (SAST/secrets/IaC/SCA), `deploy.yml`
(build→Trivy→deploy), `security-tests.yml` (post-deploy DAST + regression),
hardened `Dockerfile.paymenter`, segmented `docker-compose.yml`, reverse-proxy +
ModSecurity virtual patches, Ansible hardening, Portainer monitoring, docs.

**Validated locally (on the Windows host via Docker):**
- Image builds; runs **non-root** (`nginx`, uid 100), storage `775`, no baked
  secrets, HEALTHCHECK present.
- Full stack came up healthy; **14/14 edge regression tests passed** against a
  live local instance (include-block 400, admin+cart rate-limit 429, CORS scoped,
  HTTP→HTTPS 301, secure cookies).
- All SAST/secret/IaC gates verified to both **catch and fail** on planted bugs.

**NOT yet run / unproven (this is the point of the VM work):**
- The pipeline has **never executed as orchestrated GitHub Actions** (no runner
  was registered until the VM lab).
- The **deploy job, Ansible host-hardening (nftables/systemd/certs), and
  post-deploy DAST (ZAP/Nikto/config-audit)** have never run on a real host.
- Maturity gaps still open: actions pinned to tags/`@main` not SHAs; no branch
  protection / deploy approval; `GITHUB_TOKEN` not scoped per job.

## Architecture / lab
5-VM VirtualBox topology with a **true DMZ for production**. Full detail +
IP scheme + traffic matrix in **`docs/network-topology.md`**. Summary:
`Runner (10.0.20.10)`, `Staging (10.0.20.20, internal-only)`,
`Prod-DMZ (proxy/WAF, 10.0.10.30 public)`, `Prod-App (10.0.40.31 internal)`,
`Attacker/Kali (10.0.10.10)`. Management network `10.0.20.0/24` connects the
Runner to the servers for SSH/Ansible deploys.

## How to work with this repo
Local, non-runner validation (what was used to verify things on the host):
```bash
# Build the hardened image
docker build -f docker/Dockerfile.paymenter \
  --build-arg PAYMENTER_REPO=https://github.com/HaidenVeno/Paymenter.git \
  --build-arg PAYMENTER_REF=fix/upgrade-configoptions-injection -t paymenter:local .

# Semgrep gate exactly as CI runs it (ERROR-severity is the gate)
docker run --rm -v "$PWD/security/semgrep/rules:/rules:ro" -v "<app>:/src:ro" \
  semgrep/semgrep semgrep scan --config /rules --config p/default \
  --config p/owasp-top-ten --severity ERROR --error /src

# Edge regression suite against a running stack
docker run --rm --network <docker-net> -v "$PWD/security/tests:/tests" -w /tests \
  -e BASE_URL=https://<host> -e VERIFY_TLS=false python:3.12-slim \
  sh -c "pip install -q -r requirements.txt && pytest -m edge -v"
```

## Gotchas already discovered (don't re-learn these)
- **php-fpm as non-root** can't write its default `error_log`
  (`/usr/local/var/log` is root-owned). `docker/paymenter/www.conf` points fpm +
  worker logs at `/proc/self/fd/2`. If you see nginx 502 + php-fpm "exited too
  quickly", check this.
- **Local port-remap for testing:** host port 80 was occupied, so the proxy was
  remapped via a compose override with `ports: !override` (Compose merges port
  lists otherwise). `nginx -t` also resolves upstream hostnames, so add
  `--add-host paymenter:127.0.0.1` when testing the reverse-proxy config alone.
- **Semgrep calibration:** `p/default`+`p/owasp-top-ten` flags ~38 mostly-WARNING
  findings on the app (Symfony non-literal-redirect FPs Lab 4 documented) but
  **0 at ERROR severity** — hence the ERROR-only gate. Gitleaks: 0 leaks on the
  app; Hadolint + Trivy config: clean on the hardened Dockerfile.
- Windows/Git Bash mangles paths in `docker run`/`openssl` — prefer PowerShell or
  `MSYS_NO_PATHCONV=1` for absolute container paths (N/A once on Linux).

## Next up — Phase 1 (Runner + Staging)
Goal: get the whole pipeline running end-to-end against **Staging**, and fix the
breakage that surfaces (expect some — deploy/Ansible/DAST have never run).

1. On the Runner VM: install Docker + Node + Claude Code; clone this repo;
   register the GitHub Actions runner via `scripts/runner-up.sh`
   (`REPO=HaidenVeno/Paymenter-CICD`).
2. **Refactor `deploy.yml` for remote deploy:** it currently assumes
   runner == deploy target (Ansible `inventory.ini` was `localhost`/local). It
   must now deploy to **Staging over SSH** via the management network. Inventory
   is updated to the mgmt IPs; wire SSH keys Runner→Staging.
3. Base-provision Staging (Docker, user) from the Runner over `mgmtnet`.
4. Run `ci.yml`, then `deploy.yml` → Staging, then `security-tests.yml` (DAST +
   regression + config-audit) against `https://10.0.20.20`.
5. Set `paymenter.homelab.local → 10.0.20.20` in the relevant hosts files so the
   cert SAN + DAST target resolve.

Then Phase 2 (Prod-DMZ + Prod-App, approval-gated promotion) and Phase 3
(Attacker/Kali external validation). See `docs/checklist.md` for the rubric
tracker and `docs/test-justification.md` for gate rationale.
