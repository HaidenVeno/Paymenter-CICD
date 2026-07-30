# Paymenter DevSecOps Pipeline

**WAS705 Final Project — Group 8.** A GitHub Actions pipeline that statically
analyzes, builds, scans, hardens, deploys, and continuously security-tests the
[Paymenter](https://github.com/Paymenter/Paymenter) application, driven by the
findings from Labs 1–5.

## On-premise architecture justification

Execution happens entirely on a **self-hosted runner on our homelab**. GitHub's
cloud is used only as:
- the **code host** (this pipeline repo; the app lives in our fork),
- the **orchestration trigger** (Actions events), and
- the **notification surface** (Issues).

Every job — SAST, SCA, image build, vulnerability scanning, all security tooling,
Ansible host hardening, and deployment — runs on our own hardware and never
leaves our infrastructure. The runner is a single binary managed as a systemd
service (`svc.sh`), so there is no separate build server to patch and maintain
(contrast Jenkins). Secrets live in GitHub Actions secrets and are materialized
on-host at runtime as file mounts, never baked into images.

## Layout

```
.github/workflows/   ci.yml · deploy.yml · security-tests.yml
docker/              Dockerfile.paymenter · docker-compose.yml
  paymenter/         hardened nginx/php-fpm/supervisord/entrypoint (non-root)
  reverse-proxy/     TLS termination, security headers, Lab 5 virtual patches
security/
  semgrep/rules/     custom rules for the two bugs `auto` missed
  eslint-security/   eslint-plugin-security flat config
  zap/               ZAP baseline rules
  tests/             pytest regression suite (Stage 3) + config-audit.sh
ansible/playbooks/   harden · secrets · certs (nftables + DOCKER-USER)
docs/                test-justification · maintenance · checklist · runner-setup
evidence/            developer-engagement (redacted; raw is gitignored)
```

## How the findings flow into the pipeline

| Lab finding | Where it's enforced |
|---|---|
| `?include=` bypass (L3 §6.8 / L5 §2.2) | Semgrep rule + edge 400 block + `test_include_permission_bypass` |
| Config-option mass assignment (L3 §2.3) | Semgrep rule + `test_mass_assignment` |
| Admin API rate limit (L5 §2.3) | reverse-proxy `limit_req` + `test_admin_rate_limiting` |
| Coupon brute-force (L5 §2.4) | reverse-proxy `limit_req` + `test_coupon_bruteforce` |
| CORS wildcard (L5 §2.5/§5.1) | reverse-proxy ACAO rewrite + `test_cors_scoping` |
| RBAC self-escalation (L4 §1.2/§3.6) | `test_rbac_wildcard` |
| Remember-cookie MFA bypass (L5 §3.8) | `test_remember_mfa_bypass` |
| Session expiry / secure cookie (L4 §1.7) | `test_session_expiry` |
| OAuth secret / key exposure (L4 §2 / L5 §3.1) | `test_oauth_key_perms` + `config-audit.sh` |
| Coupon race condition (L3 §2.5, open) | `test_coupon_race_condition` (xfail) |
| 777 perms, root container, no TLS (L5 §3.x) | `Dockerfile.paymenter` + compose + Ansible |
| Vulnerable dependencies (L4 §6.3) | Dependency-Check + Trivy |

## Getting started

1. **Register the runner + secrets** → [docs/runner-setup.md](docs/runner-setup.md).
2. Push to a branch → `ci.yml` runs SAST/SCA.
3. Push to `main` → `deploy.yml` builds the hardened image, Trivy-scans it, runs
   Ansible hardening, and `docker compose up`.
4. On deploy success → `security-tests.yml` runs the regression suite + ZAP +
   Nikto + config audit against the live instance.

Status per rubric line: [docs/checklist.md](docs/checklist.md).

## Build order (as executed)

Repo skeleton → runner → SAST/SCA → hardened image + compose → build/scan/deploy
→ Ansible → regression suite → notifications → post-deploy validation → docs.
