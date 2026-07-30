# Test Justification (Report Part 1.3)

For each automated control: what it is, which Lab 1–5 finding it maps to, the
threat it addresses, and how it reduces risk. Threshold choices that gate the
build are called out because the rationale is graded.

## Pipeline gate thresholds (why these numbers)

| Gate | Threshold | Rationale |
|---|---|---|
| Semgrep custom rules | `--error` (fail on ANY finding) | These rules encode Lab 3/4/5 findings we already triaged as real. A hit means a fix regressed — zero tolerance is correct. |
| Semgrep registry packs | report-only | Lab 4 §3.1 measured 47 findings that were overwhelmingly Symfony non-literal-redirect false positives, and the packs caught **neither** business-logic bug. Gating on them would train the team to ignore red builds. Kept as an artifact for manual review. |
| OWASP Dependency-Check | `--failOnCVSS 7` (High+) | Matches the Snyk criticals/highs Lab 4/5 found in the composer tree (symfony/mailer, filament, phpseclib via passport). High+ is actionable; lower severities are reported not gated. |
| Trivy image scan | report HIGH+CRITICAL, **fail on unfixed CRITICAL** | Distinguishes "known but unfixable base-image noise" from "critical and patchable." `ignore-unfixed` avoids blocking on CVEs with no upstream fix. |
| ZAP baseline | `FAIL` on CSP/XFO/XCTO/HSTS/CORS rules | These map directly to the header/CORS findings (Lab 5 §2.5, §3.8). Everything else is WARN. |

## Static analysis (Stage 2)

### Custom rule: `paymenter-upgrade-configoption-mass-assignment`
- **Finding:** Lab 3 §2.3 / Lab 4 mass-assignment in `Upgrade.php::doUpgrade()`.
- **Threat:** T-30 (config-option injection); an authenticated customer submits
  arbitrary `config_option_id`s not offered by the product, mutating service
  state (STRIDE: Tampering, Elevation).
- **Why custom:** Lab 4 §3.1 proved Semgrep `auto` flagged this file only for an
  unrelated redirect and missed the actual bug. Business-logic authz can't be
  caught by generic taint rules, so we assert the allowlist guard's presence.
- **Risk reduction:** reintroducing the vulnerable loop (removing the
  `in_array($optionId, $allowed)` check) fails CI before merge.

### Custom rule: `paymenter-allowedincludes-permission-bypass`
- **Finding:** Lab 3 §6.8 / Lab 4 10.1 / Lab 5 §2.2, `ApiController::allowedIncludes()`.
- **Threat:** Broken access control — a scoped API key reads related records
  (`?include=user`, `?include=invoices`) it has no permission for (STRIDE:
  Information Disclosure).
- **Why custom:** Semgrep `auto` returned **zero** findings here. The bug is a
  type-confusion in a permission check (`in_array` over a nested assoc array),
  invisible to generic rules. We flag the value-search anti-pattern.
- **Risk reduction:** the known-bad pattern cannot reappear silently.

### Custom rule: `paymenter-world-writable-chmod-777`
- **Finding:** Lab 5 file-permission theme (upstream `chmod 777` on storage).
- **Threat:** Tampering/EoP via world-writable app dirs and secret files.
- **Risk reduction:** any Dockerfile/entrypoint/Ansible change reintroducing 777
  fails CI.

### ESLint (`eslint-plugin-security`)
- **Finding:** Lab 4 §3.2. First-party JS scope is only `themes/default/js`.
- **Rules:** `detect-eval-with-expression`, `detect-non-literal-fs-filename`
  (the two Lab 4 checked), promoted to errors.
- **Risk reduction:** guards against introducing `eval`/dynamic-path sinks in the
  only hand-written JS.

## Software Composition Analysis (Stage 2)
- **Finding:** Lab 4 §6.3 / Lab 5 §5.3 Snyk results (criticals in symfony/mailer,
  filament; high in phpseclib via `laravel/passport`).
- **Threat:** A06 Vulnerable & Outdated Components.
- **Risk reduction:** Dependency-Check gates High+ CVEs in composer/npm manifests
  on every push; Trivy gates the built image. Lab 5 noted the composer issue
  count drifts up as new CVEs publish (32 issues/516 paths), so continuous
  scanning — not a one-time review — is the control.

## Image & deployment hardening (Stage 5)
- **Non-root (Lab 5 §3.3):** image runs as `nginx`; nginx binds 8080; the root
  `crond` scheduler is replaced by supervised `schedule:work`. Asserted by
  `config-audit.sh` check 5 and `test_oauth_key_perms.py`.
- **Secrets not baked (Lab 5 §3.1/§3.4):** APP_KEY/DB_PASSWORD are `*_FILE`
  mounts, generated create-once by Ansible with 600 perms. The §3.4 lesson —
  never flip `encrypted => true` against live plaintext without a migration — is
  encoded as a warning in `test_oauth_key_perms.py`.
- **TLS/segmentation:** reverse proxy terminates HTTPS, forces 301 redirect
  (§3.8), sets `SESSION_SECURE_COOKIE=true`; three Docker networks
  (frontend/app/db, db internal) isolate the data tier.

## Runtime regression suite (Stage 3)

Each maps 1:1 to a Lab finding; see `security/tests/README.md` for the table.
The `@edge` tests assert the four Lab 5 virtual patches (include-block, admin
rate-limit, cart rate-limit, CORS scoping) and forced-HTTPS/headers — enforced
at the proxy so they gate on every deploy. Auth-dependent tests assert the app
fixes (RBAC, remember-cookie MFA bypass, mass-assignment, session expiry) and
activate once their seed credentials are wired as secrets.

### Open finding (tracked, not gated)
- **Coupon race condition (Lab 3 §2.5):** no virtual patch exists yet (missing
  row locking). Encoded as `xfail` so it surfaces in reports without failing the
  build; convert to a hard gate when the fix lands.
