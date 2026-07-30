"""Lab 4 s1.6.2 / Lab 5 s3.8 — paymenter_remember cookie as full MFA bypass.

Before the fix, presenting ONLY a valid `paymenter_remember` cookie (no session,
no password, no 2FA) yielded HTTP 200 on the full admin panel. The fix discards
the remember-cookie fallback for admin routes, so /admin now redirects (302).

Requires REMEMBER_COOKIE (a captured value); skips otherwise.
"""
import pytest


@pytest.mark.needs_auth
def test_remember_cookie_alone_cannot_reach_admin(http, base_url):
    import os
    remember = os.environ.get("REMEMBER_COOKIE")
    if not remember:
        pytest.skip("REMEMBER_COOKIE not set — configure to enable this test")

    # Clean client: only the remember cookie, nothing else.
    r = http.get(
        f"{base_url}/admin",
        headers={"Cookie": f"paymenter_remember={remember}"},
    )
    assert r.status_code != 200, (
        "GET /admin returned 200 with only a paymenter_remember cookie — the "
        "MFA-bypass fix (Lab 5 s3.8) has regressed. Expected a redirect."
    )
    assert r.status_code in (301, 302, 303, 307, 308, 401, 403), (
        f"Unexpected status {r.status_code} for remember-only /admin access."
    )
