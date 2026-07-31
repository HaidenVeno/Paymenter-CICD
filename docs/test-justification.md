# Test Justification (Report Part 1.3)

For each automated control: what it is, which Lab 1–5 finding it maps to, the
threat it addresses, and how it reduces risk. Threshold choices that gate the
build are called out because the rationale is graded.

## Pipeline gate thresholds (why these numbers)

The tool set follows the widely-used free DevSecOps stack (Semgrep, Gitleaks,
Hadolint, Trivy, Dependency-Check, ZAP). Every gate below was **calibrated
against the real app** so it passes on current code but fails on a regression —
the thresholds are not guesses, they were measured (see "Calibration" below).

| Gate | Threshold | Rationale |
|---|---|---|
| Semgrep — custom rules | `--error` (fail on ANY finding) | These encode Lab 3/4/5 findings we triaged as real; a hit means a fix regressed — zero tolerance. Run against the app *and* the pipeline's own `docker`/`ansible`/`scripts` (the chmod-777 rule). |
| Semgrep — `p/default` + `p/owasp-top-ten` | **gate on ERROR severity only** | `p/default` is Semgrep's ~600-rule low-FP default (catches injection, `eval`, `unserialize`). Measured: the full set flags 38 mostly-WARNING findings on our app (dominated by the Symfony non-literal-redirect FPs Lab 4 found), but **0 at ERROR severity** — so ERROR-only passes today yet still fires on real command injection/`eval`. |
| Semgrep — `p/security-audit` + `p/secrets` | report-only | The noisier packs; archived as a SARIF artifact, not gated (Lab 4 §3.1 rationale). |
| Gitleaks (secrets) | fail on any leak | Industry-standard secret scanner; catches hardcoded tokens Semgrep's rules allowlist (verified: caught Stripe/GitHub tokens a Semgrep secret scan ignored). Measured **0 leaks** on the current app, so gating is safe. Noise paths allowlisted in `.gitleaks.toml`. |
| Hadolint (Dockerfile) | `failure-threshold: warning` | Dockerfile best-practice linter. The hardened image passes clean after fixing DL4006 (pipefail); commonly-waived rules (DL3018 apk pinning, DL3066 named-user uid) are ignored in `.hadolint.yaml`. |
| Trivy config (IaC/container) | fail on HIGH/CRITICAL | Validates the Dockerfile hardening (non-root USER, pinned base, HEALTHCHECK) and fails if it regresses. Measured **0 misconfigurations** today. |
| OWASP Dependency-Check (SCA) | `--failOnCVSS 7` (High+) | Matches the Snyk criticals/highs Lab 4/5 found in the composer tree (symfony/mailer, filament, phpseclib via passport). |
| Trivy image scan | report HIGH+CRITICAL, **fail on unfixed CRITICAL** | Distinguishes unfixable base-image noise from critical+patchable. `ignore-unfixed` avoids blocking on CVEs with no fix. |
| ZAP baseline (DAST) | `FAIL` on CSP/XFO/XCTO/HSTS/CORS rules | Map directly to the header/CORS findings (Lab 5 §2.5, §3.8). Everything else WARN. |

### Calibration (measured, not assumed)
Empirically verified with each tool before gating, so the pipeline is green on
current code and only reddens on a real problem:
- Semgrep `p/default`+OWASP: **38 findings** total on the app (mostly WARNING
  Symfony-redirect FPs) → **0 at ERROR severity**. Gate on ERROR.
- Gitleaks: **0 leaks** on the app; **caught** planted Stripe/GitHub tokens.
- Hadolint: hardened Dockerfile **passes** after the DL4006 pipefail fix.
- Trivy config: **0 misconfigurations** on the hardened Dockerfile.
- Coverage cross-check: a planted OS-command-injection + `eval` was **missed by
  the narrow packs but caught by `p/default`**, and the JS `eval` was caught by
  ESLint (build-failing) — documenting that generic SAST is a layered net, not a
  guarantee (matches Lab 4 §3.1: it missed both business-logic bugs).

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
