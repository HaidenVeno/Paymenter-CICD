"""Lab 4 s1.7 / Lab 5 s3.8 — session expiry + secure-cookie enforcement.

Lab 4 confirmed inactivity/logout/password-change session invalidation already
work. Lab 5 added forced-HTTPS and SESSION_SECURE_COOKIE=true. These tests
assert the cookie-hardening effects (edge-enforced / config-enforced) and, when
an expired cookie is supplied, that it is rejected.
"""
import os
import pytest


@pytest.mark.edge
def test_http_redirects_to_https(base_url):
    # Force plain HTTP regardless of BASE_URL scheme.
    import requests, urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    host = base_url.split("://", 1)[-1]
    r = requests.get(f"http://{host}/", allow_redirects=False, timeout=15, verify=False)
    assert r.status_code in (301, 308), (
        f"Plain HTTP did not 301->HTTPS (got {r.status_code}) — forced-HTTPS "
        f"redirect (Lab 5 s3.8) regressed."
    )
    assert r.headers.get("Location", "").startswith("https://"), "Redirect target is not https://"


@pytest.mark.edge
def test_session_cookie_is_secure(http, base_url):
    r = http.get(f"{base_url}/login")
    set_cookie = r.headers.get("Set-Cookie", "")
    if "paymenter_session" not in set_cookie:
        pytest.skip("No paymenter_session Set-Cookie on /login in this response")
    # The session cookie must carry Secure (SESSION_SECURE_COOKIE=true).
    seg = [c for c in set_cookie.split(",") if "paymenter_session" in c]
    assert any("Secure" in s for s in seg), (
        "paymenter_session Set-Cookie is missing the Secure attribute "
        "(Lab 5 s3.8)."
    )


@pytest.mark.needs_auth
def test_expired_session_cookie_rejected(http, base_url):
    expired = os.environ.get("EXPIRED_COOKIE")
    if not expired:
        pytest.skip("EXPIRED_COOKIE not set — configure to enable this test")
    r = http.get(f"{base_url}/dashboard", headers={"Cookie": f"paymenter_session={expired}"})
    assert r.status_code != 200, (
        "Expired session cookie granted access to /dashboard — session "
        "expiry (Lab 4 s1.7.1) regressed."
    )
