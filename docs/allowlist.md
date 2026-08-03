# Pipeline Allowlist — every scan exception and why

This catalogs every deliberate exception, allowlist entry, and threshold
choice across the security pipeline: what's exempted, from which gate, and
the reasoning. Anything not listed here that a gate skips is a bug, not a
decision — check `CLAUDE.md`'s gotchas section first.

## Gitleaks — `.gitleaks.toml`

| Path | Reason |
|---|---|
| `.git/`, `vendor/`, `node_modules/` | Dependency/VCS internals, not first-party content. |
| `.env.example` | Template file — placeholder values by definition, not real secrets. |
| `app/tests/Feature/Auth/LoginTest.php` | Synthetic reCAPTCHA site/secret key pair used only to exercise the captcha-enabled login path in tests. Verified against the source (Phase 1) — not a real registered credential, and reCAPTCHA site keys are public-by-design anyway (embedded in front-end HTML). Scoped to this one file, not all of `tests/`, so a real secret committed elsewhere still gets caught. |

## Semgrep — `.github/workflows/ci.yml` (`semgrep` job)

- **Blocking ERROR gate excludes `Dockerfile` and `.github`** within the
  scanned `app` tree (`--exclude 'Dockerfile' --exclude '.github'`). The app
  fork's own Dockerfile and CI tooling aren't what this pipeline builds from
  (we use `docker/Dockerfile.paymenter`) or hardens — findings there (missing
  `USER`, `chmod 777`) are real but out of this pipeline's control. Still
  scanned and archived by the unscoped report-only step two down, just can't
  block the pipeline.
- **`ignore-unfixed` is not used here** (that's a Trivy concept) — Semgrep's
  exclusion is path-based, not vulnerability-based.

## Trivy — `ci.yml` (`trivy-config`) and `deploy.yml` (`trivy-scan`)

- **`ignore-unfixed: true`** on both: don't gate on CVEs with no available
  fix — nothing actionable to do about those today, and gating would make
  the pipeline permanently red for issues outside anyone's control until an
  upstream vendor patches. Re-evaluate if a CVE with no fix turns out to be
  practically exploitable in this deployment's context.
- **`deploy.yml` gates on CRITICAL only** (`severity: CRITICAL`, separate
  from the HIGH+CRITICAL *report* step) — HIGH findings are visible in the
  uploaded SARIF artifact but don't block deploys. Documented threshold, see
  `docs/test-justification.md`.

## OWASP Dependency-Check — `ci.yml` (`dependency-check`)

- **`--failOnCVSS 7`** — gates on CVSS ≥ 7.0 (i.e. HIGH+CRITICAL-equivalent),
  not every finding. Matches the Trivy severity threshold for consistency
  across SCA and image scanning.
- **`--enableRetired`** — includes retired/deprecated CVE analyzers rather
  than silently skipping them. More noise, fewer blind spots; deliberate
  trade-off toward completeness.

## Hadolint — `.hadolint.yaml`

| Rule | Reason |
|---|---|
| `DL3018` (pin apk package versions) | Alpine package versions are tied to the base image digest and rotate frequently; pinning every `apk` package is brittle and commonly waived project-wide. The base image itself is digest-pinned (`docker/Dockerfile.paymenter`), which is the real supply-chain control. |
| `DL3066` (non-numeric USER) | We intentionally run as the named `nginx` user (resolves to a pinned uid, see below) — false positive for this hardening pattern. |

## CSP — `docker/reverse-proxy/conf.d/security-headers.conf`

- **`script-src`/`style-src` allow `'unsafe-inline'` and (script-src only)
  `'unsafe-eval'`.** Filament/Livewire ship inline event handlers and
  Alpine.js evaluates expressions via `new Function()` (`x-data`, `x-show`,
  etc.) — a strict nonce-based CSP would need custom nonce middleware and
  auditing every Blade/Livewire component, a materially larger effort than
  closing the "no CSP at all" gap ZAP's baseline scan flagged (`10038`).
  Verified via a direct ZAP re-scan after adding this header: the CSP
  finding clears (0 FAIL-NEW), asset loading unaffected. Tightening to
  nonces is a reasonable follow-up, not required for Phase 1.
- Everything else in the policy (`object-src 'none'`, `frame-ancestors
  'self'`, `base-uri 'self'`, no wildcard origins) is as strict as the
  inline/eval requirement allows.

## Internal DMZ->App TLS trust — `docker/reverse-proxy/conf.d/paymenter-dmz.conf`

- **Phase 2 true-DMZ split**: Prod-DMZ's edge nginx reaches Prod-App's
  `app-edge` over the `prodint` link via HTTPS with a self-signed certificate
  (CN/SAN `prod-app.internal`, no public CA — see `ansible/playbooks/certs.yml`
  + `group_vars/prod_app.yml`'s `tls_hostname` override).
- **Pinned, not bypassed**: `proxy_ssl_verify on` + `proxy_ssl_trusted_certificate`
  (a copy of that exact cert's public half, distributed by
  `ansible/playbooks/trust-app-cert.yml`) + `proxy_ssl_name` is used instead of
  `proxy_ssl_verify off`. This is deliberately the stricter option — a
  compromised/misconfigured host on `prodint` still can't MITM the hop with an
  arbitrary self-signed cert, it would need *this specific* cert's private key.
  `proxy_ssl_verify off` would have been simpler (no cert distribution step)
  and was considered, but rejected as weaker for no real savings.
- **Network segmentation is the backstop, not the primary control.**
  `harden.yml`'s DOCKER-USER rule already restricts Prod-App's 443 to
  Prod-DMZ's prodint address specifically (`10.0.40.30/32`) — cert pinning is
  defense-in-depth on top of that, not a substitute for it.

## Local registry — `docker/docker-compose.registry.yml`

- **Purpose**: `deploy.yml` builds and Trivy-scans one image; `promote-prod.yml`
  needs to deploy the *exact same bytes* to Prod-App, not rebuild. A local
  registry (`registry:2`) lets the digest travel by reference instead of
  `docker save`/`docker load` — same content-addressable guarantee, but
  reusable across a workflow boundary (deploy.yml push → promote-prod.yml
  pull, potentially days apart).
- **Location**: on the Runner (already the trusted build host). Published
  port bound to the Runner's mgmt IP specifically (`10.0.20.10:5000:5000`,
  not `0.0.0.0`), which alone scopes reachability to mgmtnet without a new
  nftables ruleset — the Runner has never been a `harden.yml` target and
  doesn't need to become one for this.
- **TLS: self-signed cert, pinned on every consumer's Docker trust store**
  (`/etc/docker/certs.d/registry.homelab.local:5000/ca.crt` on `runner`,
  `staging`, `prod_app` — Prod-DMZ never runs `paymenter`, doesn't need it).
  Considered and rejected `insecure-registries` for the same reason
  `proxy_ssl_verify off` was rejected for the DMZ→App hop: mgmtnet-only
  reachability is a real control, but pinning costs little extra and doesn't
  rely on network position being the *only* thing standing between a
  plaintext pull and an attacker who's already gotten onto mgmtnet.
- Verified: fingerprint match across Runner/Staging/Prod-App's trusted
  copies, and a manual push+pull-by-digest from all three before wiring
  anything into CI.

## Approval gate — GitHub Environment `production`

- **Private + Free-plan repos can't get required-reviewers or wait-timer
  protection rules from GitHub** (`422`: "billing plan supports the
  required reviewers protection rule") — both are Team/Enterprise-only for
  private repos, though free on public ones. Made the repo **public** to
  unlock this rather than settle for an ungated environment or a paid
  upgrade; confirmed via a full-history Gitleaks scan (not just the
  working tree — `docker/secrets/certs/privkey.pem` triggers a hit in
  `--no-git` mode but is confirmed gitignored/never committed) that nothing
  sensitive was in the 21-commit history before flipping visibility.
- `promote-prod.yml`'s `environment: production` is what GitHub actually
  gates on the required reviewer — `workflow_dispatch` alone (no push
  trigger) is a meaningful gate on its own (only a collaborator with write
  access can trigger it), but the Environment protection rule adds a real
  pause-for-review step GitHub enforces, not just an access-control implication.

## Fixed bug: DOCKER-USER rules blocking container-originated traffic

- **Not an allowlist entry — a real bug found and fixed** while validating
  the Phase 2 compose split, documented here because it explains a change to
  `ansible/playbooks/templates/docker-user-fw.sh.j2` that's easy to mistake
  for a policy choice.
- The DROP/RETURN rules originally matched on destination **port** alone
  (e.g. `--dports 80,443`), with no destination **address** restriction. That
  silently blocked any container's own *outbound* call to another host on
  the same port — invisible on Staging (nothing there ever made such a
  call), but it broke Prod-DMZ's reverse-proxy reaching Prod-App's
  `app-edge:443` over `prodint` the moment the true-DMZ split needed it.
  Symptom was a clean 504 after nginx's connect-timeout, with *nothing* in
  nginx's own error log — the packet never left the DOCKER-USER chain.
- **Fix**: added `-d 172.16.0.0/12` (Docker's default bridge-network address
  pool) to both branches. Docker's own DNAT for published ports rewrites the
  destination to the container's bridge-internal IP before DOCKER-USER ever
  sees the packet, so restricting `-d` to that range scopes the rule to
  "inbound to one of my published container ports" — an outbound call to a
  real external IP (Prod-App's `10.0.40.31`, or a real payment gateway's API)
  never matches it. Also fixes a related silent no-op: the old cleanup
  `iptables -D ... -j DROP` omitted the protocol/port match the real rule
  had, so it never actually deleted anything — stale duplicate rules stacked
  up on every `harden.yml` re-run. The delete commands now mirror their
  insert exactly.

## Removed: stock Ubuntu `nginx` package on Prod-DMZ

- Prod-DMZ came with the distro `nginx` package active and enabled
  (bound to 0.0.0.0:80), left over from whatever "basic connectivity" setup
  preceded Ansible provisioning — not something `provision.yml`/`docker.yml`
  ever installed. It conflicted directly with the `reverse-proxy` container's
  own port 80/443 binding (`docker compose up` failed with "address already
  in use"). Stopped and disabled (not purged — reversible) since this host's
  entire purpose is running the containerized proxy on those ports.

## Container identity — `docker/Dockerfile.paymenter`

- **`nginx` user pinned to uid/gid `10000`/`10000`**, deliberately outside
  Alpine's system-account range. Not a scan exception, but the same spirit:
  a documented, deliberate deviation from "whatever `apk` assigns" because
  the default drifts on package changes (see `CLAUDE.md`'s Phase 1 gotchas —
  this exact drift broke secret-file ownership once already this project).
  `ansible/playbooks/secrets.yml`'s `owner: "10000"` must match this if it's
  ever repinned.

## Not yet resolved (tracked, not silently accepted)

- **ZAP baseline was failing the pipeline on WARN-level findings, not just
  FAIL-level** — `zaproxy/action-baseline` without `-I` fails the job on
  *any* alert regardless of `rules.tsv`'s own WARN/FAIL classification. The
  claim that "ZAP baseline only fails on FAIL-level by default" was wrong
  until this was found and fixed (`cmd_options: '-I'`); the first real
  automated `security-tests.yml` run surfaced it (`FAIL-NEW: 0, WARN-NEW:
  7`, job still failed).
- Of the 7 WARN findings that scan surfaced, two are now actually resolved:
  - **`X-Powered-By: PHP/<version>` leak (10037)** — fixed with
    `proxy_hide_header X-Powered-By;` in `proxy-params.conf` (shared across
    every proxying location in `paymenter.conf`/`paymenter-dmz.conf`/
    `app-edge.conf`), same technique already used there for
    `Access-Control-Allow-Origin`.
  - **`Cookie No HttpOnly Flag` on `XSRF-TOKEN` (10010)** — not a bug to fix,
    reclassified `IGNORE` in `rules.tsv` alongside the existing 10054 entry
    for the same cookie. `XSRF-TOKEN` is deliberately JS-readable (Laravel
    echoes it back as the `X-XSRF-TOKEN` header for CSRF protection) —
    making it HttpOnly would *break* CSRF protection, not improve it.
- **Still open, deliberately deferred:**
  - **COEP/COOP/CORP headers missing (90004, x6)** — enabling
    `Cross-Origin-Embedder-Policy` requires every cross-origin resource the
    page loads to send correct CORP/CORS headers. For a payment platform
    that will likely need to embed real payment-gateway widgets/iframes,
    turning this on without auditing every third-party integration risks
    silently breaking payment flows — worse than the finding itself.
  - **CSP: Failure to Define Directive with No Fallback (10055)** — flagged
    against the CSP header added earlier this session. `object-src`/
    `frame-ancestors`/`base-uri`/`form-action` are already explicitly set;
    needs investigation into exactly which directive ZAP considers
    fallback-less before changing the policy, not a guess.
  - Purely informational, not actionable: `Non-Storable Content` (10049 —
    pages correctly sending `Cache-Control: no-store`, which is *good*
    practice being misflagged), `Re-examine Cache-control Directives` on
    `robots.txt` (10015), `Session Management Response Identified` (10112 —
    ZAP noting it found the session cookie for its own analysis, not a
    vulnerability).
- **`security/tests/auth/test_oauth_key_perms.py`** skips with "paymenter
  container not found / docker unavailable" — same runner-vs-deploy-target
  assumption `config-audit.sh` had until Phase 1's fix, just not yet ported
  to this test file. Skips gracefully (doesn't fail the suite), so it's
  lower priority than the fixes that were actually blocking.
