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
- The pipeline repo lives on GitHub as **`HaidenVeno/Paymenter-CICD`**. On the
  **Windows host**, push over HTTPS (Git Credential Manager supplies the
  HaidenVeno token) — the SSH key there authenticates as a *different* account,
  `hveno_seneca`, so SSH pushes 404 from Windows specifically. On the **Runner
  VM**, SSH works fine and is what's actually configured (`~/.ssh/id_ed25519`,
  `gh auth login` via device flow) — this 404 gotcha does not apply there.

## Current state (2026-08) — Phase 1 fully closed, merged to main
**Built (all 10 stages scaffolded):** `ci.yml` (SAST/secrets/IaC/SCA), `deploy.yml`
(build→Trivy→deploy→Staging over SSH), `security-tests.yml` (post-deploy DAST +
regression), hardened `Dockerfile.paymenter`, segmented `docker-compose.yml`,
reverse-proxy + ModSecurity virtual patches, Ansible hardening, Portainer
monitoring, docs.

**Runner is registered and live** (systemd service
`actions.runner.HaidenVeno-Paymenter-CICD.CICD-Runner-hveno`, `AS_SERVICE=1`).
`phase1/staging-remote-deploy` is merged into `main` — Phase 1 is done, not
pending.

**Validated via real GitHub Actions on the self-hosted runner (not just
locally):**
- `ci.yml`: all 6 jobs (semgrep, eslint-security, gitleaks, hadolint,
  trivy-config, dependency-check) green.
- `deploy.yml`: `build` → `trivy-scan` → `deploy` all green — the deploy job
  actually SSHes to Staging, transfers the scanned image, brings the compose
  stack up, and health-checks it. `https://paymenter.homelab.local/` returns
  `200` off a CI-driven deploy, not a manual one.
- `security-tests.yml`: **fully clean.** `gate`, `regression-tests` (14
  passed / 14 skipped / 0 failed — skips are the documented Stage 3 auth-secret
  gap, not bugs), `post-deploy-nikto`, and `post-deploy-config-audit` (all
  checks pass) are all green. `post-deploy-zap`'s "CSP Header Not Set" finding
  is fixed (see below) — confirmed via a direct manual ZAP re-scan
  (`FAIL-NEW: 0`), not yet re-confirmed via a full CI run (deliberately, to
  avoid re-running the ~30min pipeline for a config-only change — see
  `docs/allowlist.md` for the CSP policy rationale).
- Ansible host-hardening (`provision.yml`→`docker.yml`→`secrets.yml`→
  `certs.yml`→`harden.yml`, run in that order) has executed for real against
  Staging, including the nftables/DOCKER-USER firewall reload — no lockout,
  confirmed idempotent on repeat runs.

**New reference doc:** `docs/allowlist.md` catalogs every scan exception in
the pipeline (gitleaks paths, semgrep scope exclusion, Trivy/Dependency-Check
thresholds, hadolint waivers, the CSP policy trade-off) with rationale — check
there before assuming an exception is a bug.

**Still open:**
- `security-tests.yml`'s auth-layer tests need secrets wired (Stage 3 in
  `docs/checklist.md`) to stop skipping.
- `auth/test_oauth_key_perms.py` still checks the container locally instead
  of over SSH to the deploy target (same class of bug `config-audit.sh` had
  until Phase 1's fix, just not yet ported here) — skips gracefully, doesn't
  fail the suite, so it's cosmetic rather than blocking.
- Maturity gaps: no branch protection / deploy approval; `GITHUB_TOKEN` not
  scoped per job; `STAGING_BECOME_PASS` (Ansible become password, needed for
  `deploy.yml`'s provisioning step) is a plaintext-in-secret password rather
  than a sudoers NOPASSWD entry on Staging — works, but the latter would be
  cleaner.
- Phase 2 (Prod-DMZ + Prod-App) — see "Next up" below; those VMs don't exist
  yet, so this is still a standing-up-infrastructure task, not a pipeline task.

## Architecture / lab
5-VM VirtualBox topology with a **true DMZ for production**. Full detail +
IP scheme + traffic matrix in **`docs/network-topology.md`**. Summary:
`Runner (10.0.20.10)`, `Staging (10.0.20.20, internal-only)`,
`Prod-DMZ (proxy/WAF, 10.0.10.30 public)`, `Prod-App (10.0.40.31 internal)`,
`Attacker/Kali (10.0.10.10)`. Management network `10.0.20.0/24` connects the
Runner to the servers for SSH/Ansible deploys.

**Runner VM identity note:** the Runner's hostname was `CICD-Runner` from the
start of Phase 1 work, but its mgmt IP (`10.0.20.10`) briefly answered as
`CoreRouter` earlier in its life (a prior repurposing, unrelated leftover
hostname/`/etc/hosts` entry) — if you ever see that name again, it's stale
cruft to clean up, not a sign something's misconfigured. Same happened to
Staging (`VPNClientWorkstation` → `CoreRouter` → `staging`).

**Runner VM tooling** (installed during Phase 1, not covered by a fresh-OS
assumption): Docker CE (official apt repo, not Ubuntu's `docker.io`), Node.js,
Ansible + `ansible.posix`, `sshpass`, GitHub CLI (`gh`, authenticated via
device flow as `HaidenVeno`), `python3-pip` (missing initially — found via
`security-tests.yml`'s `regression-tests` job failing `pip: command not
found`). `hveno` is in the `docker` group — **note this only takes effect for
NEW login sessions** (fresh SSH connections, the runner service's own
process); a long-lived shell from before the `usermod` won't see it, use
`sg docker -c "..."` there instead of assuming plain `docker` works.

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
  **0 at ERROR severity** — hence the ERROR-only gate. This app-tree number has
  since drifted (69 on the report-only pass as of Phase 1, and the ERROR gate
  now legitimately fires 4 — see below), so treat "0/~38" as historical
  calibration evidence, not a live invariant to assert against. Gitleaks: 0
  leaks on first-party app code (2 synthetic reCAPTCHA test keys in
  `LoginTest.php` are allowlisted, not a leak); Hadolint + Trivy config: clean
  on the hardened Dockerfile.
- Windows/Git Bash mangles paths in `docker run`/`openssl` — prefer PowerShell or
  `MSYS_NO_PATHCONV=1` for absolute container paths (N/A once on Linux).

### Phase 1 gotchas (found running the pipeline for real for the first time)
These were all genuinely never-executed-before bugs — the pipeline had *never*
run as orchestrated Actions until this phase, so none of this was catchable
without a real runner + real deploy target.
- **Self-hosted runners reuse the same `_work` directory across every job and
  every run** (unlike GitHub-hosted ephemeral runners). Any Docker-based
  action/step that writes as root (dependency-check, gitleaks, trivy, ZAP,
  nikto, semgrep-via-docker) leaves root-owned files behind that block the
  *next* job's `actions/checkout` with `EACCES: permission denied, unlink`.
  Fixed with a reusable composite action, `.github/actions/reclaim-workspace`,
  run as `if: always()` in every job that touches Docker — `sudo chown -R`
  back to the runner user. Needs a narrowly-scoped
  `/etc/sudoers.d/hveno-ci-chown` NOPASSWD entry for just `/usr/bin/chown` on
  the Runner (not a blanket NOPASSWD).
- **Standalone `docker compose` (non-Swarm) does NOT honor a service's
  `secrets: uid/gid/mode` overrides** — that's Swarm-only. File-type secrets
  are a straight bind-mount of the host source file; host-side ownership is
  exactly what the container sees. `secrets.yml` locks the three secret files
  to the app container's runtime uid, mode `0400`.
- **That runtime uid is NOT stable across image rebuilds by default.** Alpine
  assigns system uids/gids by package-install order; an `apk upgrade` (or any
  package change) can silently reshuffle `nginx`'s uid — this happened for
  real when the OpenSSL CVE fix's `apk upgrade` bumped nginx from `100/101` to
  `101/102` and broke every secret read in the very next deploy. Fixed by
  deleting and recreating `nginx` with an explicit uid/gid (`10000/10000`) far
  outside Alpine's system-account range, in `docker/Dockerfile.paymenter`.
  `secrets.yml`'s `owner:` must match whatever this is currently pinned to.
- **Ansible play-level `vars:` outrank `group_vars` in the precedence order.**
  `harden.yml` used to hardcode `management_cidr`/`allowed_web_sources`
  directly as play vars — a `group_vars/staging.yml` override would have
  silently lost, and applying the wrong (default) CIDR would nftables-lock the
  Runner out of Staging's SSH the instant the play ran. Defaults now live in
  `group_vars/all.yml`; per-env overrides in `group_vars/<group>.yml` actually
  win because the play no longer redeclares the same names.
- **`nft flush ruleset` is global, not scoped to your own table** — Docker's
  own nftables tables (`DOCKER-USER` et al) live in the same ruleset with no
  ordering guarantee against `nftables.service` at boot. `flush ruleset` in
  `harden.yml`'s template broke `DOCKER-USER` immediately on first apply.
  Fixed: `add table inet filter` + `flush table inet filter` (scoped) in
  `ansible/playbooks/templates/nftables.conf.j2`.
- **`cap_drop: [ALL]` (the reverse-proxy and paymenter services both use it)
  strips root's `DAC_OVERRIDE`** — even a container running as UID 0 is then
  subject to normal file-permission checks, same as any non-root process. The
  cert directory (`docker/secrets/certs`) must be owned by whatever identity
  actually reads it (root, since the reverse-proxy never drops off UID 0, just
  loses the override capability) — `certs.yml` declares `owner: root`
  explicitly now instead of relying on whoever happened to create the dir.
- **`secrets` context is not allowed in a step-level `if:`.** All three
  workflows had `if: ${{ secrets.DISCORD_WEBHOOK_URL != '' }}` on the Discord
  notify step — a hard schema violation that silently produced a run with
  **zero jobs** and no useful error beyond "workflow file issue" in the UI.
  Blocked every workflow in the repo, not just the step itself. Fixed by
  moving the secret into `env:` and the emptiness check into the shell script.
  Caught with `actionlint` — install it before touching workflow YAML again,
  it makes GH-specific schema violations obvious.
- **`aquasecurity/trivy-action@0.28.0` doesn't resolve** — the repo's tags are
  `v`-prefixed (`v0.28.0` exists, bare `0.28.0` doesn't). Now SHA-pinned to
  `v0.36.0` in both `ci.yml` and `deploy.yml`.
- **ESLint 9's flat config treats anything outside the CWD's directory tree as
  "outside the base path" and silently ignores it.** Running
  `eslint --config eslint.config.mjs "../../app/..."` from
  `security/eslint-security` matched zero lintable files (exit 2). Fix: run
  from the workspace root instead, with paths relative to that (no `../../`).
- **`workflow_run` only fires based on the workflow file version on the
  repo's *default branch*** — `security-tests.yml` won't auto-chain after
  `deploy.yml` on a feature branch even if both files are identical to what's
  on `main`. Not a bug; dispatch manually (`workflow_dispatch`) when working
  off-branch, and expect it to "just work" once merged.
- **`pip` is not installed by default** even though `python3` is — the Runner
  had `/usr/bin/python3` but no `pip`/`pip3` until `apt-get install
  python3-pip`. `security-tests.yml`'s `regression-tests` job needs it.
- Semgrep's own `run:` steps used `pip install semgrep` — nothing on the
  runner provides that; switched to `docker run semgrep/semgrep` for all three
  invocations (matches what's actually validated elsewhere in this doc).

## Next up — Phase 2 (Prod-DMZ + Prod-App)
Phase 1 (Runner + Staging) is done and merged to `main` — see "Current state"
above. Starting Phase 2:
1. Stand up Prod-DMZ + Prod-App VMs per `docs/network-topology.md`'s IP
   scheme (`10.0.10.30` / `10.0.40.31`, mgmt `10.0.20.30` / `10.0.20.31`).
   `ansible/inventory.ini` already has groups for both. **Not yet started —
   these VMs don't exist yet**, so this begins as infra standup, not a
   pipeline change.
2. Approval-gated promotion: build once on Staging, promote the *same* scanned
   image to prod (don't rebuild) — the image-transfer mechanism from Phase 1
   (`docker save | ssh ... docker load`) generalizes directly.
3. `provision.yml`'s `mgmt_iface` default (`enp0s8`) may not hold for
   Prod-DMZ, which has more NICs than Runner/Staging — check and override via
   `host_vars` if needed.
4. `group_vars/staging.yml`'s pattern (per-env `management_cidr` /
   `allowed_web_sources` override) needs a `group_vars/prod_dmz.yml` and
   `group_vars/prod_app.yml` equivalent — don't let `harden.yml` fall back to
   `group_vars/all.yml`'s default CIDR against prod hosts, same lockout risk
   Staging had in Phase 1.
5. Decide the promotion trigger: manual `workflow_dispatch` with an
   environment-protection rule (GitHub Environments + required reviewers) is
   the natural fit given `deploy.yml`'s existing structure — not yet built.

Then Phase 3 (Attacker/Kali external validation). See `docs/checklist.md` for
the rubric tracker and `docs/test-justification.md` for gate rationale.
