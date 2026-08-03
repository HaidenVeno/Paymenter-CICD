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

## Container identity — `docker/Dockerfile.paymenter`

- **`nginx` user pinned to uid/gid `10000`/`10000`**, deliberately outside
  Alpine's system-account range. Not a scan exception, but the same spirit:
  a documented, deliberate deviation from "whatever `apk` assigns" because
  the default drifts on package changes (see `CLAUDE.md`'s Phase 1 gotchas —
  this exact drift broke secret-file ownership once already this project).
  `ansible/playbooks/secrets.yml`'s `owner: "10000"` must match this if it's
  ever repinned.

## Not yet resolved (tracked, not silently accepted)

- **ZAP WARN-level findings** (`Cookie No HttpOnly Flag`, `X-Powered-By`
  header leak, `Cross-Origin-Embedder-Policy` missing, CSP directives
  without a fallback) — surfaced by the same re-scan that validated the CSP
  fix. Not gated on (ZAP baseline only fails on FAIL-level by default), but
  real and worth a future pass.
- **`security/tests/auth/test_oauth_key_perms.py`** skips with "paymenter
  container not found / docker unavailable" — same runner-vs-deploy-target
  assumption `config-audit.sh` had until Phase 1's fix, just not yet ported
  to this test file. Skips gracefully (doesn't fail the suite), so it's
  lower priority than the fixes that were actually blocking.
