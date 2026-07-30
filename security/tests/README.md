# Security regression suite

Scripted, repeatable versions of the Lab 3/4/5 manual findings. Each test
asserts the **effect** of a fix or virtual patch and fails loudly on regression.

## Running

```bash
pip install -r requirements.txt
BASE_URL=https://paymenter.homelab.local pytest
```

## Two tiers of test

- **`@edge` tests** need only `BASE_URL`. They assert reverse-proxy-enforced
  virtual patches (include-block, admin rate limit, cart rate limit, CORS
  scoping, forced HTTPS, security headers). These run green on a fresh deploy.
- **`@needs_auth` / `@needs_docker` tests** require seeded credentials or docker
  access, supplied via environment variables (wire them as GitHub secrets).
  They **skip** with an explicit reason until configured — a skip is not a pass,
  but it is not a false failure either.

## Environment variables

| Var | Enables |
|---|---|
| `BASE_URL` | everything (default `https://paymenter.homelab.local`) |
| `VERIFY_TLS` | set `true` to verify certs (default false for self-signed) |
| `ADMIN_API_TOKEN` | admin-scoped API tests |
| `LOWPRIV_API_TOKEN`, `LOWPRIV_ROLE_ID` | RBAC self-escalation |
| `CUSTOMER_COOKIE` | cart/checkout/upgrade tests |
| `REMEMBER_COOKIE` | paymenter_remember MFA-bypass |
| `EXPIRED_COOKIE` | session-expiry rejection |
| `UPGRADE_SERVICE_ID`, `BOGUS_CONFIG_OPTION_ID` | upgrade mass-assignment |
| `CHECKOUT_PRODUCT_ID`, `CHECKOUT_OPTION_FIELD` | config-injection fuzz |
| `RACE_COUPON_CODE`, `RACE_COUPON_MAX_USES` | coupon race condition |
| `PAYMENTER_CONTAINER` | docker-exec checks (else auto-discovered) |

## Finding coverage (Stage 3 table)

| Test file | Finding |
|---|---|
| `api/test_include_permission_bypass.py` | `?include=` bypass (Lab 5 §2.2) |
| `api/test_admin_rate_limiting.py` | admin API rate limit (Lab 5 §2.3) |
| `api/test_cors_scoping.py` | CORS wildcard (Lab 5 §2.5 / §5.1) |
| `api/test_mass_assignment.py` | upgrade config-option injection (Lab 3 §2.3) |
| `auth/test_rbac_wildcard.py` | RBAC self-escalation (Lab 4 §1.2 / §3.6) |
| `auth/test_remember_mfa_bypass.py` | remember-cookie MFA bypass (Lab 5 §3.8) |
| `auth/test_session_expiry.py` | session expiry + secure cookie (Lab 4 §1.7) |
| `auth/test_oauth_key_perms.py` | OAuth secret / key exposure (Lab 4 §2 / Lab 5 §3.1) |
| `fuzzing/test_coupon_bruteforce.py` | coupon brute-force (Lab 5 §2.4) |
| `fuzzing/test_coupon_race_condition.py` | coupon race condition (Lab 3 §2.5, open) |
| `fuzzing/test_config_injection.py` | config option injection (Lab 3 §2.2) |
