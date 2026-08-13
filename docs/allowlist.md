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

**Confirmed via a real automated `security-tests.yml` run** (not just local
validation): `FAIL-NEW: 0, WARN-NEW: 5, IGNORE: 1, PASS: 61` — `X-Powered-By`
now passes outright, the `XSRF-TOKEN` HttpOnly finding is correctly counted
under `IGNORE` instead of `WARN`, and the job passes end to end.

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
- **`security/tests/auth/test_oauth_key_perms.py`** now runs for real
  (fixed in a later session, see below) — it used to skip with "paymenter
  container not found / docker unavailable" because it shelled out to a
  *local* `docker`, which never finds anything since the Runner and Staging
  are different hosts (same runner-vs-deploy-target class of bug
  `config-audit.sh` had until Phase 1's fix). Note: `oauth-private.key`/
  `oauth-public.key` live outside every named volume in
  `docker-compose.app-core.yml` (only `storage/logs` and `storage/app/
  public` are volumes), so they're in the container's ephemeral layer and
  are lost on every recreate — confirmed multiple times (initially, after a
  full lab reboot, and again after a VM crash). **Now fixed in
  `docker/paymenter/entrypoint.sh`**: it generates the keys with
  `passport:keys` if absent and forces `600` — importantly *after* the
  blanket `chmod -R 775 /app/storage`, which was itself leaving the private
  key world-readable (found live at `775`, failing the perms assertion).

## Auth secrets wiring (Stage 3 regression suite) — findings

Walked through wiring the `security-tests.yml` auth-dependent secrets
against real Staging data (real users/API keys/sessions, not placeholders).
Full detail in `docs/checklist.md` Stage 3; summary here:

- **Real, currently unpatched vulnerability**: `test_remember_mfa_bypass.py`
  fails for real. A request to `/admin` carrying *only* a
  `paymenter_remember` cookie (no session, no password, no 2FA) returns the
  actual Filament Dashboard at `HTTP 200` — the exact MFA-bypass class Lab 5
  s3.8 was supposed to have fixed. Confirmed via both a manual `curl` and
  the pytest run, on Staging's current deployed code. This needs a decision
  from whoever owns the app fork (`HaidenVeno/Paymenter`) — it's flagged
  here, not silently patched, since fixing app logic is a bigger call than
  wiring a secret.
- **Discovered the real auth mechanism differs from what the test suite's
  env-var names imply**: the admin API (`/api/v1/admin/*`) is authorized by
  a custom `ApiKey` model (SHA-256-hashed token, `type`/`permissions`
  columns), *not* Laravel Passport OAuth tokens — despite Passport being
  present and used elsewhere (`oauth-*.key`, `passport:client`). A Passport
  personal-access token looks superficially valid but gets a genuinely
  different `401` ("provided API key is invalid or has been disabled") from
  a custom middleware, not Passport's own error. `ADMIN_API_TOKEN` is now a
  real `ApiKey` row with the full real permission set (33 `admin.<resource>.
  <action>` strings pulled from the actual `FormRequest` classes — there's
  no wildcard support in this system, unlike the web-session RBAC's
  `hasPermission()`).
- **`/api/v1/admin/roles` was never registered as an API route at all**
  (`routes/api.php`'s `Route::apiResources([...])` list has categories,
  credits, users, products, services, orders, invoices, invoice-items,
  tickets, ticket-messages — no roles). Confirmed live: `404`, `"route
  api/v1/admin/roles/1 could not be found"`. Role editing is a **Filament
  admin-panel** page (`admin/roles/{record}/edit`), not a REST API resource
  — RBAC there is enforced against the web session, not the `ApiKey`
  permission system. `test_rbac_wildcard.py` has since been rewritten
  against the real mechanism (see below) rather than left pointed at a
  route that doesn't exist.
- **Checkout/Upgrade/Cart are Livewire components, not classic forms** —
  `/services/{id}/upgrade`, `/products/{category}/{product}/checkout`
  (nested, not the flat `/checkout/{id}` the tests originally assumed), and
  `/cart` are all registered `GET`-only; real interactivity goes through
  Livewire's own AJAX update protocol, not a plain form `POST`. The
  original `test_mass_assignment.py`, `test_config_injection.py`, and
  `test_coupon_race_condition.py` all `POST`ed to guessed URLs that 404'd —
  which happened to satisfy their assertions (`status_code < 500`, not in
  `(200,201,302)`) without exercising anything real.

**Follow-up session: all 5 of the above rewritten to drive the real
mechanism, not left skipping.** `security/tests/livewire_helpers.py` speaks
Livewire v3's actual protocol: GET the page, pull the target component's
`wire:snapshot` (HTML-entity-decoded JSON) and CSRF token out of the HTML,
then `POST {base}/paymenter/update` — a custom-named alias for Livewire's
update route (`AppServiceProvider::boot()`), not the framework default
`/livewire/update` — with `{_token, components: [{snapshot, updates,
calls}]}`; `continue_livewire_call()`/`post_snapshot_update()` chain a
follow-up action off a *prior* response's snapshot instead of re-GETing the
page, both for protocol fidelity (a real browser reuses server-returned
state across an interaction) and because re-GETing `/cart` on every step of
a multi-step flow collides with the `limit_req zone=cart` virtual patch
below. `security/tests/remote_helpers.py` adds SSH-based ground truth
(container/DB queries against the deploy target, not the Runner) for
assertions the admin API can't answer — `remote_mysql()` base64-encodes SQL
before it ever touches a shell, after a real statement (a JSON permissions
array with embedded double quotes) got silently mangled by nested shell
quoting across the SSH-login-shell + `docker exec sh -c` layers.

- `test_config_injection.py` — 6 payload cases (xss/sqli/cmdi/ssti/path/
  nullbyte) against the checkout config-option field, checking the
  *rendered HTML fragment* (not the raw JSON body, which necessarily echoes
  submitted state as part of normal hydration). All 6 pass genuinely now.
- `test_mass_assignment.py` — drives `services.upgrade`'s real `doUpgrade`
  action with a config_option_id outside the product's allowlist, then
  verifies via direct DB query that no `service_configs` row was ever
  persisted for it. Passes — the allowlist protection in
  `App\Livewire\Services\Upgrade::doUpgrade()` is genuinely correct.
- `test_coupon_race_condition.py` — N distinct customer accounts each add
  the product to cart and apply a **dedicated** race-test coupon (never a
  real one), then all fire `checkout()` concurrently; verified via DB count
  of `services.coupon_id`. Since every CI run permanently adds real
  redemptions to whatever coupon is used, a fixed `max_uses` would only ever
  prove anything on the coupon's first run — this pins `max_uses` to
  `current_count + N_slots` immediately before each race (SSH DB write), so
  the test stays meaningful indefinitely instead of degrading once the
  coupon "fills up". Kept `xfail(strict=False)` — Lab 5 explicitly declined
  to patch the missing row lock, and a real network hop's timing means the
  race isn't guaranteed to be caught on every run either way.
- `test_rbac_wildcard.py` — uses a low-privilege **session cookie**
  (`LOWPRIV_COOKIE`, not an API token) against the real Filament edit page.
  **This found a genuine, currently-exploitable full-admin self-escalation**
  — see the dedicated section below. Reverts the DB state in a `finally`
  block regardless of pass/fail, so running this test never leaves an
  account actually escalated afterward.
- `test_oauth_key_perms.py` — switched from local `docker exec` to
  `remote_helpers.py`'s SSH-based container resolution, so it actually runs
  in CI (previously always skipped there, silently, since the Runner never
  has the container locally). **Found a second genuine finding** — see
  below.

New env vars this added: `LOWPRIV_COOKIE`, `CHECKOUT_CATEGORY_SLUG`,
`CHECKOUT_PRODUCT_SLUG`, `CHECKOUT_CONFIG_OPTION_ID`, `CHECKOUT_PLAN_ID`,
`RACE_CUSTOMER_COOKIES` (comma-separated, >= 2 accounts), `RACE_COUPON_CODE`,
`RACE_COUPON_SLOTS`. `ADMIN_API_TOKEN`/`LOWPRIV_API_TOKEN` and their
`admin_token`/`lowpriv_token` fixtures are now unused by any test file (no
API resource exists for what they were built to authorize) — left in
`conftest.py` rather than removed as part of this rewrite, since deleting
them wasn't part of the task.

## New findings from the Livewire rewrite

- **RBAC self-escalation, currently unpatched (Lab 4 s1.2/10.2, Lab 5
  s3.5-s3.6)**: a "viewer" staff account holding only `admin.roles.viewAny`/
  `admin.roles.view` (no `admin.roles.update`) can grant **itself** wildcard
  (`*`) permissions by editing its own role through the Filament panel.
  Live-verified end-to-end, then reverted: the write reaches the `roles`
  table (`permissions` went from `["admin.roles.viewAny","admin.roles.
  view"]` to `["*"]`). Root cause: `App\Admin\Resources\RoleResource::
  canEdit()` is hardcoded to `return $record->id !== 1;` — it never
  consults `RolePolicy::update()` (which does check `admin.roles.update`),
  so any user who can reach the Roles resource can edit any role except the
  seeded id=1. `App\Models\Role` has no save-time guard rejecting `'*'` for
  a non-seeded role either; the `CheckboxList` form field only constrains
  the browser UI, and posting `data.permissions: ["*"]` directly via the
  Livewire update protocol bypasses it entirely. This contradicts what the
  test previously assumed was already fixed — that fix either regressed or
  was never applied to this fork. Flagged to the project owner; decision was
  to land the regression test now (documenting the gap honestly) and treat
  the actual app-code fix as follow-up work, same deferral as the MFA
  bypass.
- **OAuth client secrets still plaintext (Lab 4 s2.1, claimed-fixed s3.4)**:
  `oauth_google_client_secret`, `oauth_github_client_secret`, and
  `oauth_discord_client_secret` are all still declared `'type' => 'text'`
  in `app/Classes/Settings.php`. The claimed fix (`'type' => 'password',
  'encrypted' => true`, applied via migration) isn't present in this fork.
- **Fixed a real bug in the test harness itself**: `conftest.py`'s `http`
  fixture tried to force `allow_redirects=False` by wrapping
  `s.request`, but `requests.Session.get()`/`.post()` inject
  `allow_redirects=True` into kwargs themselves *before* calling
  `.request()` — so the fixture's `setdefault()` never actually saw a
  missing key for any test calling `.get()`/`.post()` (the common case).
  `test_expired_session_cookie_rejected` was silently chasing the app's
  redirect target instead of just inspecting the 302, and erroring out
  trying to connect to it directly. Fixed by overriding `.get`/`.post`/
  `.patch`/`.put`/`.delete` directly instead of relying on `.request()`
  alone.
