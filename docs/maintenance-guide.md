# Maintenance Guide (Report Part 4)

How to operate the pipeline day to day. Written per-component while it was built.

## Pipeline map

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | every push / PR | Semgrep, ESLint-security, Gitleaks, Hadolint, Trivy-config, Dependency-Check + notify |
| `deploy.yml` | push to `main` | build hardened image → Trivy → Ansible (Staging) → compose up → push scanned digest to the local registry |
| `security-tests.yml` | after `deploy.yml` succeeds, or manual | pytest regression suite + ZAP + Nikto + config-audit (against Staging) |
| `promote-prod.yml` | manual (`workflow_dispatch`) only | pulls the last Staging-validated digest onto Prod-App, brings up Prod-App + Prod-DMZ, confirms end-to-end |

Commit messages containing `[skip ci]` suppress `ci.yml`/`deploy.yml`'s push
triggers — use this for doc/config-only changes that don't need a full
~30min pipeline run (Nikto is the long pole).

## Topology this pipeline manages

Four hosts, not one:

| Host | Role | Compose file |
|---|---|---|
| Runner | builds, scans, hosts the local registry | `docker-compose.registry.yml` |
| Staging | full stack, one VM, internal-only, `deploy.yml`'s target | `docker-compose.yml` |
| Prod-DMZ | reverse-proxy/WAF only, the sole public-facing host | `docker-compose.dmz.yml` |
| Prod-App | app+db+cache, no public NIC | `docker-compose.app.yml` (includes `docker-compose.app-core.yml`) |

Staging and the Prod-DMZ/Prod-App split are **independent** — Staging's
`docker-compose.yml` is untouched by the DMZ split and keeps its own
Docker-network-local proxy→app hop. Full network detail:
`docs/network-topology.md`.

## Routine tasks

### Update the app version being built
Change the `APP_REF` repo variable (branch or SHA). The Dockerfile clones that
ref; the SAST/SCA jobs check out the same ref. No image edits needed.

### Promote a build to production
1. Confirm `deploy.yml` succeeded on `main` and pushed a digest — check the
   repo variable: `gh variable list | grep STAGING_VALIDATED_DIGEST`.
2. `gh workflow run promote-prod.yml` (optionally `-f digest=sha256:...` to
   pin a specific past build instead of the latest).
3. The run pauses at the `production` Environment gate — approve it in the
   GitHub UI (Actions → the run → Review deployments). It does **not**
   proceed on its own; that pause is the point.
4. Once approved, it pulls that exact digest onto Prod-App, brings up both
   compose stacks, and checks end-to-end through Prod-DMZ.

### Rotate secrets
Two different secret systems are in play — don't confuse them:

**Files under `docker/secrets/` (gitignored, one set per host)** — `app_key`,
`db_password`, `db_root_password`, created once by `ansible/playbooks/secrets.yml`
and never overwritten on re-run:
1. **DB passwords:** update the secret file, then update the DB user
   (`ALTER USER`) — the app reads the file at container start.
2. **APP_KEY:** rotating invalidates all existing encrypted values (including
   every session cookie and the OAuth/Passport keys — see below). Only do
   this with a re-encryption migration; otherwise treat it as immutable per
   install.

**GitHub Actions secrets/variables** (`gh secret list` / `gh variable list`):
- `STAGING_BECOME_PASS` — Ansible's sudo password for `deploy.yml`'s
  provisioning step.
- `STAGING_VALIDATED_DIGEST` (variable, not secret) — set automatically by
  `deploy.yml` after a healthy Staging deploy; read by `promote-prod.yml`.
- `ADMIN_API_TOKEN`, `REMEMBER_COOKIE`, `EXPIRED_COOKIE` — auth-dependent
  regression-test fixtures. See "Regenerate the auth test credentials" below
  if they stop working (e.g. after an `APP_KEY` rotation, which invalidates
  the cookies immediately).

### Regenerate the auth test credentials
These aren't placeholders — they're real tokens/sessions against real users
created on Staging, since `security-tests.yml`'s auth-dependent tests need
real credentials to test anything. If they go stale (session destroyed,
`APP_KEY` rotated, user deleted), regenerate like this:

**Admin API token** (`ADMIN_API_TOKEN`) — the admin API (`/api/v1/admin/*`)
is authorized by a custom `ApiKey` model (SHA-256-hashed token,
`type`/`permissions` columns) — **not** Passport OAuth, despite Passport
being present for other things. A Passport personal-access token will
*look* valid but get rejected by this middleware.
```bash
docker exec -e HOME=/tmp docker-paymenter-1 php artisan tinker --execute="
\$plain = bin2hex(random_bytes(32));
\$key = App\Models\ApiKey::create([
  'name' => 'sectest-admin', 'token' => hash('sha256', \$plain),
  'user_id' => 1, 'type' => 'admin', 'enabled' => true,
  'permissions' => array_map(fn(\$p) => 'admin.' . \$p, [
    'tickets.view','tickets.update','tickets.delete','tickets.create',
    'services.view','services.create','services.update','services.delete',
    'ticket_messages.view','ticket_messages.create','ticket_messages.delete',
    'products.view','invoices.update','invoices.delete','invoices.view',
    'invoices.create','credits.update','credits.create','credits.view',
    'credits.delete','users.delete','users.update','users.view',
    'users.create','invoice_items.delete','invoice_items.view',
    'invoice_items.update','invoice_items.create','categories.view',
    'orders.delete','orders.view','orders.create','orders.update',
  ]),
]);
echo \$plain;
"
```
(No wildcard support in this permission system — list every
`admin.<resource>.<action>` string explicitly, pulled from the
`$permission` property on each class under
`app/Http/Requests/Api/Admin/`.) Requires `oauth-private.key`/
`oauth-public.key` to exist first (`php artisan passport:keys` — see
warning below) even though this specific token type doesn't use Passport;
`ApiKey` creation still touches the encrypter path that needs them.

**Remember-me / expired-session cookies** (`REMEMBER_COOKIE`,
`EXPIRED_COOKIE`) — `/login` is a Livewire component, not a classic form;
log in via its real AJAX endpoint (`POST /paymenter/update` — a
custom-named alias for Livewire's update route, not the framework default
`/livewire/update`):
```python
# GET /login, extract the auth.login component's wire:snapshot + csrf-token
# from the HTML, then POST the login call:
POST /paymenter/update
X-CSRF-TOKEN: <from the page>
{"_token": "<csrf>", "components": [{
  "snapshot": "<the raw wire:snapshot, HTML-entity-decoded>",
  "updates": {"email": "...", "password": "...", "remember": true},
  "calls": [{"path": "", "method": "submit", "params": []}]
}]}
```
A successful login sets `paymenter_session` and (if `remember: true`)
`paymenter_remember` in the response `Set-Cookie` headers — use those raw
values directly as the secrets. For `EXPIRED_COOKIE`, take a fresh
`paymenter_session` cookie, decrypt it to find the underlying session ID
(`php artisan tinker --execute="echo Crypt::decrypt(urldecode('<cookie>'), false);"`
— the part after the `|` is the session ID), then invalidate it server-side
so the cookie is genuinely expired, not just malformed:
```bash
php artisan tinker --execute="app('session')->driver()->getHandler()->destroy('<session-id>');"
```

**Known gap**: `oauth-private.key`/`oauth-public.key` (`php artisan
passport:keys`) live outside every named volume in
`docker-compose.app-core.yml` — they're in the container's ephemeral layer
and will be **lost on the next recreate**. Regenerate them (see command
above) if `ApiKey` creation or anything Passport-related starts failing
with "Invalid key supplied" after a redeploy. Fixing this properly (a
volume, or generating them at provision time like `secrets.yml` does) is
tracked but not done.

### Renew TLS certs
Self-signed certs are generated by `ansible/playbooks/certs.yml` (365 days,
`tls_hostname` driven by `group_vars/<host>.yml` — **not** a play-level
default, that precedence bug bit this file once already). Four distinct
identities now exist:
- Staging / Prod-DMZ: public hostname, `paymenter.homelab.local` (the
  `group_vars/all.yml` default).
- Prod-App: `prod-app.internal` (`group_vars/prod_app.yml`) — pinned by
  Prod-DMZ via `ansible/playbooks/trust-app-cert.yml`, not CA-trusted.
- Runner: `registry.homelab.local` (`group_vars/runner.yml`) — pinned by
  every consumer (`runner`/`staging`/`prod_app`) via
  `ansible/playbooks/trust-registry-cert.yml`, written to each host's
  `/etc/docker/certs.d/registry.homelab.local:5000/ca.crt`.

For real (non-self-signed) certs, set `use_certbot=true` and a public
domain; certbot writes into the `certbot-webroot` volume via the reverse
proxy's `/.well-known/acme-challenge/` location, then symlink
`fullchain.pem`/`privkey.pem` into `docker/secrets/certs/`.

After rotating any of the pinned certs above (Prod-App's or the registry's),
re-run the corresponding `trust-*-cert.yml` playbook so consumers pick up
the new fingerprint — they compare the exact cert, not just the CN.

### Add a new regression test
Drop a `test_*.py` under `security/tests/{auth,api,fuzzing}/`, tag it `@edge`
(needs only `BASE_URL`) or `@needs_auth`/`@needs_docker`, and add a row to
`security/tests/README.md` + `docs/test-justification.md`. It runs
automatically. **Verify the route you're testing actually exists and uses
the HTTP method you expect** before wiring secrets for it — several tests
in this suite were written against routes/methods that don't match the real
app (Livewire components are `GET`-only AJAX, not classic form `POST`s; see
`docs/allowlist.md`'s "Auth secrets wiring" section for the specific
examples and how to drive Livewire's real request format).

### Add / tune a Semgrep rule
Rules live in `security/semgrep/rules/`. Keep genuine findings at `severity:
ERROR` (they gate). Validate syntax with `semgrep --validate --config
security/semgrep/rules` before pushing.

### Interpret a red build
- **Semgrep custom rule** → a Lab fix regressed; see the rule's `message`.
- **Dependency-Check / Trivy** → a High/Critical CVE; check the artifact report,
  bump the dependency or base image.
- **ZAP** → note `cmd_options: '-I'` is required in `security-tests.yml` for
  the job to fail only on FAIL-level alerts, not WARN — see
  `docs/allowlist.md` if this ever regresses.
- **config-audit** → a header/CORS/TLS/perms hardening step reverted.
- A Discord message + GitHub Issue (label `security`) is opened automatically.

## Watching the stack (Portainer)
A web GUI for container status/health/logs/stats and the network segmentation,
run as a separate management plane behind a read-only docker-socket-proxy:
```bash
docker compose -f docker/monitoring/docker-compose.portainer.yml up -d
# https://localhost:9443 on the host (or ssh -L 9443:localhost:9443 user@homelab)
```
Details + how to enable management mode: `docker/monitoring/README.md`. The
GitHub Actions tab visualizes the pipeline runs themselves (job graph + logs).

## Runner service
```bash
sudo ./svc.sh status      # health
sudo ./svc.sh stop|start  # cycle
journalctl -u actions.runner.* -f
```

## Local registry (Runner)
`registry:2`, bound to the Runner's mgmt IP only (`10.0.20.10:5000`), TLS
pinned rather than `insecure-registries`. Bring up once, not per-pipeline-run:
```bash
docker compose -f docker/docker-compose.registry.yml up -d
```
If it's ever recreated, re-run `certs.yml` against `runner` and
`trust-registry-cert.yml` before anything tries to push/pull — a fresh
container with no cert means every consumer's pinned copy stops matching.

## Firewall
Host rules: `/etc/nftables.conf` (`systemctl reload nftables`). Docker
published-port rules: `paymenter-fw.service` → `/usr/local/sbin/paymenter-fw.sh`
(inserts into the `DOCKER-USER` chain after `docker.service`). Never `iptables
-F` the Docker chains; the script only does additive inserts.

Each deploy target (Staging, Prod-DMZ, Prod-App) runs its **own** independent
copy of this — there's no shared firewall state. The `DOCKER-USER` rules
must scope by **destination** (`-d 172.16.0.0/12`, Docker's bridge-address
range), not port alone — a rule matching on port only will also silently
block a container's own *outbound* calls to that same port on another host
(found this when Prod-DMZ's reverse-proxy couldn't reach Prod-App; see
`docs/allowlist.md`).

## Logs
Container logs ship to `/var/log/paymenter` on the host (`harden.yml`). App logs
persist in the `app-storage-logs` volume. `docker compose logs -f paymenter` for
live tailing.

## Backups
Persisted volumes: `db-data`, `app-var`, `app-storage-public`. Snapshot these
before a major upgrade. The DB volume holds all customer/service state. This
applies per-host now — Staging and Prod-App each have their own independent
set of these volumes.
