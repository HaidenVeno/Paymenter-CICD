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

## Phase 2 (Prod-DMZ + Prod-App) — true DMZ split, manually validated end-to-end
Prod-DMZ (`10.0.20.30` mgmt / `10.0.10.30` attacknet / `10.0.40.30` prodint,
hostname `ips-waf-proxy`) and Prod-App (`10.0.20.31` mgmt / `10.0.40.31`
prodint, hostname `Production-Server`) exist and are provisioned. **Not yet
merged to a branch or wired into CI** — this was all done manually against
real infrastructure, mirroring how Phase 1 validated Staging by hand before
`deploy.yml`/CI existed. See `/home/hveno/.claude/plans/snug-soaring-treasure.md`
for the full design.

**What's built and verified:**
- `provision.yml` gained `extra_netplan_ifaces` (host_vars-driven) to persist
  NICs beyond mgmt. `host_vars/prod-dmz.yml` / `host_vars/prod-app.yml` pin
  the prodint/attacknet addressing — **adapter-to-network mapping is NOT
  symmetric between the two VMs** (Prod-DMZ's prodint NIC is `enp0s9`,
  Prod-App's is `enp0s3`; confirmed empirically, not by assumption — VirtualBox
  only requires both ends share an Internal Network *name*, not a slot number).
- `harden.yml`/`nftables.conf.j2` gained an `is_app_tier` mode
  (`group_vars/prod_app.yml`): Prod-App has no public NIC, so instead of
  "open 80/443 to allowed_web_sources" it's "open only `app_port` (443),
  only from Prod-DMZ's prodint address". `group_vars/prod_dmz.yml` scopes
  `allowed_web_sources` to `attacknet` (`10.0.10.0/24`), not the `0.0.0.0/0`
  default.
- The single `docker-compose.yml` (Staging-only, unchanged) is split for
  Phase 2 into `docker-compose.app-core.yml` (shared paymenter/database/cache
  fragment, pulled in via Compose's `include:`), `docker-compose.app.yml`
  (Prod-App: app-core + a new `app-edge` TLS terminator), and
  `docker-compose.dmz.yml` (Prod-DMZ: `reverse-proxy` only, upstream now
  `10.0.40.31:443` instead of the Docker-network name `paymenter:8080`).
- **DMZ→App hop is SSL-enforced and cert-pinned**, not `proxy_ssl_verify
  off`: `app-edge`'s self-signed cert (CN `prod-app.internal`, via
  `certs.yml`'s now-per-host `tls_hostname`) is fetched to Prod-DMZ by a new
  `ansible/playbooks/trust-app-cert.yml` and pinned with
  `proxy_ssl_trusted_certificate` + `proxy_ssl_name`. Verified fingerprints
  match exactly on both sides.
- End-to-end proven: `curl https://paymenter.homelab.local/` from Prod-DMZ's
  own host returns the real Paymenter login page (HTTP 200), routed through
  the pinned HTTPS hop to Prod-App.

**Two real bugs found and fixed while validating this (see
`docs/allowlist.md` for full detail — don't re-learn these):**
- `certs.yml` had the same play-vars-outrank-group_vars bug `harden.yml` hit
  in Phase 1 (`tls_hostname` was hardcoded as a play `vars:`, silently
  defeating `group_vars/prod_app.yml`'s override). Fixed by moving the
  default to `group_vars/all.yml`.
- **`docker-user-fw.sh.j2`'s DOCKER-USER rules matched on destination port
  alone**, with no destination-address scoping — this silently dropped a
  container's own *outbound* call to another host on the same port (Prod-DMZ
  reverse-proxy → Prod-App:443), not just inbound traffic to its own
  published ports. Invisible on Staging (nothing there ever made an outbound
  call like this); would also have silently blocked paymenter calling a real
  payment gateway's HTTPS API. Fixed with `-d 172.16.0.0/12` (Docker's
  default bridge-address pool) on both the app-tier and web-tier branches.
  Also fixed a related silent no-op in the same file: the DROP rule's
  cleanup `iptables -D` omitted match criteria the real rule had, so it
  never actually deleted anything — re-running `harden.yml` stacked up
  stale duplicate rules every time. Both hosts' stale rules were manually
  cleaned up this session; the fix is now idempotent (verified: two
  consecutive runs, no duplicates).
- Also removed (stopped + disabled, not purged): a stock Ubuntu `nginx`
  package pre-installed on Prod-DMZ that was silently bound to port 80,
  conflicting with the `reverse-proxy` container's own port binding.

Compose split is committed on `phase2/dmz-app-split` (PR #9, not yet merged).

## Approval-gated production promotion (local registry + `promote-prod.yml`)
Built on branch `phase2/registry-promotion` (stacked on `phase2/dmz-app-split`
— it depends on `docker-compose.app.yml`/`docker-compose.dmz.yml` existing).

- **Local registry** (`docker/docker-compose.registry.yml`): `registry:2` on
  the Runner, port bound to the Runner's mgmt IP specifically
  (`10.0.20.10:5000`, not `0.0.0.0`) — that alone scopes reachability to
  mgmtnet, no new nftables ruleset needed. TLS via `certs.yml` against the
  `runner` host (`group_vars/runner.yml`'s `tls_hostname:
  registry.homelab.local`); the cert is **pinned** on every consumer
  (`ansible/playbooks/trust-registry-cert.yml` → `/etc/docker/certs.d/registry.homelab.local:5000/ca.crt`
  on `runner`/`staging`/`prod_app`), not `insecure-registries` — same
  reasoning as rejecting `proxy_ssl_verify off` earlier. Verified: fingerprint
  match across all three hosts, manual push+pull-by-digest before touching
  CI. Evidence in `evidence/phase2-promotion/`.
- **`deploy.yml`** now pushes the Trivy-scanned, health-checked image to the
  registry (by digest, after the existing health-check step — never a
  built-but-unvalidated image) and records it as the repo variable
  `STAGING_VALIDATED_DIGEST` via `gh variable set` (needs `permissions:
  actions: write` on that job).
- **New workflow `promote-prod.yml`**: `workflow_dispatch`-only (optional
  `digest` input, defaults to `STAGING_VALIDATED_DIGEST`), gated by
  `environment: production`. Pulls that exact digest onto Prod-App, brings up
  `docker-compose.app.yml`, health-checks it, then brings up
  `docker-compose.dmz.yml` on Prod-DMZ and confirms end-to-end.
- **The repo is now public** (`gh repo edit --visibility public`) — required
  because GitHub's required-reviewers/wait-timer Environment protection
  rules need GitHub Team/Enterprise for *private* repos (free on public
  ones), and this repo is on the Free plan. Confirmed via a full-history
  Gitleaks scan (21 commits, not just the working tree) that nothing
  sensitive was in history before flipping visibility — see
  `docs/allowlist.md`. The `production` GitHub Environment exists with
  HaidenVeno as the required reviewer (`gh api .../environments/production`).
- **Deliberately unchanged**: Staging's own deploy path (`docker save | ssh |
  docker load`) — the registry only needed to hold a copy for later
  promotion, not replace how Staging gets its image.

**Not yet done:**
- End-to-end test of `promote-prod.yml` itself (trigger it, confirm the
  review-gate actually pauses the run, approve, confirm Prod-App+Prod-DMZ
  serve the promoted digest) — next immediate step.
- Repointing `provision.yml`'s `paymenter_hostname`/`paymenter_ip` defaults
  (currently Staging's) at Prod-DMZ's public identity — a deliberate one-time
  cutover decision, waits until Phase 3 proves segmentation (explicit
  instruction: Phase 3 before any hostname cutover).
- None of the registry/promotion work is committed yet.

Then Phase 3 (Attacker/Kali external validation) — needs its own VM stand-up
(same as Prod-DMZ/Prod-App did), not yet started. See `docs/checklist.md` for
the rubric tracker and `docs/test-justification.md` for gate rationale.
