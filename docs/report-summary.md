# Project Summary — DevSecOps Pipeline for Paymenter

Working notes for report-writing and the demonstration recording. Everything
here is drawn from what was actually built and validated against real
infrastructure — not aspirational. Where a claim needs backing, the file path
is given so it can be pulled up on camera.

## 1. What this project is

A self-hosted, on-premise DevSecOps pipeline securing **Paymenter** (a
Laravel/PHP + Livewire + Filament billing platform, forked at
`HaidenVeno/Paymenter`, branch `fix/upgrade-configoptions-injection`). GitHub
is used only as the code host and orchestration surface — every build, scan,
and deploy runs on a self-hosted GitHub Actions runner inside a 5-VM
VirtualBox lab. Nothing about job execution, security tooling, or deployment
leaves the owner's infrastructure.

Repo: `HaidenVeno/Paymenter-CICD` (now public — see §5). Durable technical
context lives in `CLAUDE.md` at the repo root; this document is the
report/demo-oriented companion to it.

## 2. Lab architecture

A true DMZ topology, not a flat network — the point being to demonstrate that
a compromised edge component doesn't hand an attacker the database.

| VM | Role | Mgmt IP | Other IPs | Public? |
|---|---|---|---|---|
| **Runner** | CI/CD orchestration, image builds, local registry | `10.0.20.10` | — | No |
| **Staging** | Full stack (proxy+app+db) on one VM, "soft DMZ" via Docker networks | `10.0.20.20` | — | No |
| **Prod-DMZ** | Reverse proxy + WAF only — the *only* public-facing host | `10.0.20.30` | attacknet `10.0.10.30`, prodint `10.0.40.30` | Yes |
| **Prod-App** | App + DB + cache, no public NIC at all | `10.0.20.31` | prodint `10.0.40.31` | No |
| **Attacker/Ops** | External Kali box for Phase 3 validation | — | attacknet `10.0.10.10` | (isolated) |

Full detail, traffic-policy matrix, and rationale: `docs/network-topology.md`.

## 3. Pipeline stages (rubric mapping)

Full detail and status per stage: `docs/checklist.md`. Summary — all 8
applicable stages are **Done** and validated on real infrastructure (Stage 7,
bug-disclosure process, is separate ongoing work; Stage 4's Discord webhook
is wired but not yet secret-configured):

| Stage | Workflow / component | Status |
|---|---|---|
| 0 — Repo structure | — | Done |
| 1 — Self-hosted runner | systemd service on Runner VM | Done |
| 2 — SAST/Secrets/IaC/SCA | `ci.yml` (Semgrep, ESLint-security, Gitleaks, Hadolint, Trivy-config, Dependency-Check) | Done, all 6 jobs green |
| 3 — Automated security tests | `security-tests.yml` regression suite (11 modules / 28 cases) | Done, clean run |
| 4 — Developer notification | Discord + GitHub Issue on failure | Built, webhook not yet configured |
| 5 — Hardened image + deploy | `deploy.yml` (build → Trivy → deploy) | Done, CI-driven deploy confirmed |
| 6 — Ansible + post-deploy validation | `harden.yml`/nftables, ZAP, Nikto, config-audit | Done, fully clean |
| 8 — Docs | `docs/*.md` | Done |

## 4. Phase 1 — Runner + Staging

Got the entire pipeline running for real, end to end, for the first time (it
had never executed as orchestrated Actions before this project — every bug
below was a genuine first-execution discovery, not a known issue).

**Built:** `ci.yml`, `deploy.yml`, `security-tests.yml`, hardened
`Dockerfile.paymenter` (non-root, digest-pinned base images, HEALTHCHECK),
segmented `docker-compose.yml` (frontend/app/db Docker networks), reverse
proxy with 4 WAF virtual patches, Ansible host hardening.

**Validated on the real runner, not just locally:**
- `ci.yml` — all 6 jobs green.
- `deploy.yml` — SSHes to Staging, transfers the scanned image, brings the
  stack up, health-checks it. `https://paymenter.homelab.local/` returns
  `200` from a CI-driven deploy.
- `security-tests.yml` — fully clean (`regression-tests`, `post-deploy-nikto`,
  `post-deploy-config-audit`, `post-deploy-zap` all green).
- Ansible hardening (`provision→docker→secrets→certs→harden`) — no SSH
  lockout, idempotent on repeat runs.

**Real vulnerability found and fixed:** a CRITICAL OpenSSL CVE
(CVE-2026-31789) in the base image, caught by the first real Trivy scan.
Fixed by `apk upgrade` + digest-pinning — which then caused a *second* real
bug (see §6).

**Real vulnerability found and fixed:** ZAP flagged "Content-Security-Policy
Header Not Set" (`10038`). Added a CSP header
(`docker/reverse-proxy/conf.d/security-headers.conf`) — `default-src 'self'`
with `unsafe-inline`/`unsafe-eval` scoped to `script-src` only, a deliberate,
documented trade-off (Filament/Livewire ship inline handlers, Alpine.js uses
`new Function()`) rather than an oversight. See `docs/allowlist.md`.

## 5. Phase 2 — True DMZ split (Prod-DMZ + Prod-App)

Split the single-VM Staging stack into a real DMZ: Prod-DMZ runs only the
reverse proxy/WAF (the sole public-facing host); Prod-App runs the
app/db/cache with no public NIC at all. All work was **validated manually
against real infrastructure before being wired into CI** — same discipline
as Phase 1 (prove it by hand first, automate second).

**Compose split** (`docker/docker-compose.app-core.yml` shared fragment +
`docker-compose.app.yml` + `docker-compose.dmz.yml`, pulled together via
Compose's `include:` so the app/db/cache service definitions aren't
duplicated).

**DMZ→App hop is TLS-enforced and certificate-pinned** — not
`proxy_ssl_verify off`. Prod-App's `app-edge` nginx terminates TLS with a
self-signed cert; Prod-DMZ's reverse proxy validates that *specific* cert via
`proxy_ssl_trusted_certificate` + `proxy_ssl_name`, distributed by a small
Ansible play (`ansible/playbooks/trust-app-cert.yml`) rather than a manual
copy. This was a deliberate choice over the simpler `proxy_ssl_verify off` —
network segmentation already limits who's on the internal link, but pinning
is the stricter control and cost little extra to implement.

**Firewall**: `harden.yml` gained an `is_app_tier` mode — Prod-App's
nftables/DOCKER-USER rules open only its app port, only to Prod-DMZ's
specific internal address, instead of the public-web-host default.

**End-to-end proven:** `curl https://paymenter.homelab.local/` from
Prod-DMZ's own host returns the real Paymenter login page, routed through the
pinned HTTPS hop to Prod-App.

## 6. Approval-gated production promotion

The point: the exact image Trivy-scanned and health-checked on Staging is
what reaches production — never a rebuild, never "close enough."

- **Local Docker registry** (`registry:2` on the Runner, TLS-pinned on every
  consumer's Docker trust store, reachable only over the management network).
- `deploy.yml` pushes the validated image **by digest** after Staging's
  health check passes, and records that digest as a GitHub repo variable.
- **New workflow `promote-prod.yml`**: manual `workflow_dispatch` only,
  gated by a GitHub Environment (`production`) with a required reviewer.
  Pulls the exact recorded digest onto Prod-App, brings up both compose
  stacks, and confirms end-to-end.
- **Validated for real**: dispatched the workflow, confirmed the Environment
  gate genuinely *paused* the run (zero steps executed until approved — not
  a silent pass-through), approved it, and confirmed via `docker inspect`
  that the digest running on Prod-App matched byte-for-byte what was pushed.
  Evidence: `evidence/phase2-promotion/promote-prod-e2e.txt`.
- The repo was made public specifically to unlock GitHub's required-reviewer
  Environment protection (Team/Enterprise-only for private repos on the Free
  plan) — done only after a full git-history Gitleaks scan confirmed nothing
  sensitive was ever committed.

## 7. Real bugs found and fixed during implementation

This is the strongest evidence of hands-on engineering rigor for the report —
every one of these was discovered by actually running the pipeline against
real infrastructure, not by inspection. Full detail with root cause and fix
location: `CLAUDE.md`'s "Phase 1 gotchas" and "Two real bugs found" sections,
and `docs/allowlist.md`.

**Phase 1:**
- Self-hosted runners reuse their workspace across every job — root-owned
  files from Docker-based scanning tools blocked the *next* job's checkout.
  Fixed with a reusable `reclaim-workspace` composite action.
- Standalone `docker compose` doesn't honor per-service secret uid/gid
  overrides (Swarm-only) — host-side file ownership is what the container
  actually sees.
- Alpine reassigns system uids by package-install order — an unrelated
  `apk upgrade` (the OpenSSL CVE fix) silently reshuffled the app's runtime
  uid and broke every secret read on the very next deploy. Fixed by pinning
  an explicit uid/gid outside Alpine's system range.
- Ansible play-level `vars:` silently outrank `group_vars` — a hardcoded
  default in `harden.yml` would have defeated a per-environment CIDR
  override and firewalled the Runner out of SSH the moment the play ran.
- `nft flush ruleset` is global, not scoped — it nuked Docker's own
  `DOCKER-USER` firewall chain on first apply. Fixed with a scoped
  `add table` + `flush table`.
- GitHub Actions' `secrets` context is not allowed in a step-level `if:` —
  a hard schema violation that silently produced **zero jobs**, no useful
  error, blocking every workflow in the repo.

**Phase 2 (true DMZ split):**
- Same play-vars-vs-group_vars precedence bug, this time in `certs.yml`.
- **The most subtle one**: the DOCKER-USER firewall rules matched on
  destination *port* alone, with no destination-address scoping — this
  silently dropped a container's own *outbound* call to another host on the
  same port, not just inbound traffic to its own published ports. Invisible
  on Staging (nothing there ever made an outbound call like this); it broke
  Prod-DMZ's reverse proxy reaching Prod-App the moment the true-DMZ split
  needed it, and would have silently blocked the app calling a real payment
  gateway's API in production. Fixed by scoping the rule to Docker's own
  bridge-address range.
- A stock Ubuntu `nginx` package, pre-installed on Prod-DMZ from before this
  project touched it, was silently bound to port 80 and conflicted with the
  containerized reverse proxy.

**Promotion pipeline:**
- `GITHUB_TOKEN` structurally cannot manage GitHub repo Actions variables
  under *any* `permissions:` grant — that capability needs repo-admin scope,
  which isn't grantable to the ephemeral token at all. Confirmed via a real
  failed run (`403: Resource not accessible by integration`), fixed by using
  the Runner's own persistent `gh auth` session instead.
- `workflow_dispatch` workflows must exist on the **default branch** to be
  dispatchable at all — an unmerged branch's workflow is invisible to the
  API regardless of `--ref`.
- `gh run rerun --failed` re-executes a run's *original* workflow-file
  snapshot, not the current default-branch version — a fix that looked like
  it "didn't apply" was actually just never re-evaluated.
- ZAP's baseline scan was failing the pipeline on WARN-level findings, not
  just FAIL-level, because `zaproxy/action-baseline` needs an explicit `-I`
  flag to respect its own severity classification file. An earlier
  assumption ("ZAP only fails on FAIL-level by default") was wrong and had
  to be corrected in the docs once the first real automated run surfaced it.

## 8. Security findings — final state

Confirmed via a real automated `security-tests.yml` run (not just manual
validation): `FAIL-NEW: 0, WARN-NEW: 5, IGNORE: 1, PASS: 61`.

**Fixed:**
- CSP header missing (`10038`) — added, with a documented `unsafe-inline`/
  `unsafe-eval` trade-off for the Livewire/Alpine.js stack.
- `X-Powered-By: PHP/<version>` disclosure (`10037`) — stripped at the proxy.
- CRITICAL OpenSSL CVE in the base image — patched + digest-pinned.

**Reclassified, not "fixed" (fixing would break the app):**
- `XSRF-TOKEN` cookie missing `HttpOnly` (`10010`) — deliberately
  JS-readable by Laravel's CSRF design; making it HttpOnly would break CSRF
  protection, not improve security.

**Deliberately deferred, with documented reasoning** (`docs/allowlist.md`):
- COEP/COOP/CORP headers — enabling `Cross-Origin-Embedder-Policy` requires
  every cross-origin resource to send correct CORP/CORS headers; turning it
  on without auditing future payment-gateway widget/iframe integrations
  risks silently breaking real payment flows.
- CSP "directive with no fallback" — needs investigation into exactly which
  directive before changing the policy further.
- A few purely informational ZAP findings (correct `no-store` caching on
  authenticated pages being misflagged, ZAP noting its own session-cookie
  detection) — not real issues.

## 9. What's next

- **Phase 3**: stand up the Attacker/Kali VM, run external ZAP/Nikto
  validation through the WAF from outside, and demonstrate that segmentation
  actually blocks lateral access to Prod-App/Staging/the management network.
- **Hostname cutover**: repoint `paymenter.homelab.local` from Staging to
  Prod-DMZ's public identity — deliberately waits until Phase 3 proves
  segmentation works, not done in parallel with standing up Phase 2.
- Wire the remaining maturity items: `DISCORD_WEBHOOK_URL` secret, auth-layer
  test secrets for the regression suite's currently-skipped cases.

## 10. Suggested demo walkthrough

A sequence that shows the real, validated behavior rather than just reading
code:

1. **The pipeline catching a real finding**: show `ci.yml`'s Semgrep/Gitleaks
   jobs green, then point to `docs/allowlist.md` for the *documented*
   exceptions (proof these were reviewed, not just suppressed).
2. **CI-driven deploy**: trigger or point to a `deploy.yml` run; show
   `https://paymenter.homelab.local/` responding `200` afterward — the app
   is provably running the CI-built image, not something deployed by hand.
3. **The true DMZ**: `curl` Prod-App directly from the Runner (times out —
   firewalled) vs. from Prod-DMZ (works) — demonstrates the segmentation is
   real, not just a network diagram.
4. **Certificate pinning**: `openssl x509 -fingerprint` on Prod-App's cert
   vs. Prod-DMZ's trusted copy — identical, proving the pin isn't
   decorative.
5. **The approval gate, live**: dispatch `promote-prod.yml`, show the run
   sitting at `status: waiting` with zero steps executed, approve it in the
   GitHub UI, then show it complete and `docker inspect` confirming the
   promoted digest matches what was scanned.
6. **A bug, live**: walk through one of §7's findings (the DOCKER-USER
   outbound-blocking bug is the most interesting — a security *control*
   silently breaking a legitimate feature) using the actual `iptables -L
   DOCKER-USER -n -v` output and the before/after fix.

## 11. Where the evidence lives

- `CLAUDE.md` — durable technical handoff, most detailed source of truth.
- `docs/allowlist.md` — every scan exception/threshold with rationale.
- `docs/checklist.md` — rubric-stage-by-stage status.
- `docs/network-topology.md` — full lab architecture + traffic policy.
- `docs/test-justification.md` — gate-threshold rationale.
- `evidence/phase2-promotion/` — TLS handshake, cert fingerprint match,
  push/pull-by-digest, and full promote-prod.yml end-to-end proof.
- PRs #9 (compose split) and #10 (registry + promotion) on GitHub — full
  diff history and CI check results for both.
