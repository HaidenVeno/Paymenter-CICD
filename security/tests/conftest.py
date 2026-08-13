"""Shared fixtures for the Paymenter security regression suite.

Design: every test targets the DEPLOYED instance and asserts the *effect* of a
Lab 3/4/5 fix or virtual patch. Tests that need seeded auth data skip cleanly
(with an explicit reason) when the corresponding env var is unset, so the suite
is green on a fresh deploy for the infra-enforced patches and turns red only on
a genuine regression. Wire the auth-dependent env vars up as GitHub secrets to
activate those tests.

Environment variables (all optional except BASE_URL, which has a default):
  BASE_URL              e.g. https://paymenter.homelab.local
  VERIFY_TLS            "true" to verify certs (default false; self-signed lab)
  ADMIN_API_TOKEN       full-access admin API bearer token
  LOWPRIV_API_TOKEN     restricted API token (only a narrow permission)
  CUSTOMER_COOKIE       Cookie header value for an authenticated customer
  LOWPRIV_COOKIE        Cookie header value for a low-privilege staff session
  REMEMBER_COOKIE       value of a captured paymenter_remember cookie
  EXPIRED_COOKIE        value of a known-expired paymenter_session cookie
  PAYMENTER_CONTAINER   container name/id (default: discovered via compose)
"""
import os
import ssl
import urllib3
import pytest
import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = os.environ.get("BASE_URL", "https://paymenter.homelab.local").rstrip("/")
VERIFY_TLS = os.environ.get("VERIFY_TLS", "false").lower() == "true"
ADMIN_API = "/api/v1/admin"


def _env(name):
    v = os.environ.get(name)
    return v if v else None


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture()
def http():
    s = requests.Session()
    s.verify = VERIFY_TLS
    s.headers.update({"User-Agent": "paymenter-sec-tests/1.0"})
    # Short timeouts so burst/rate tests stay fast.
    orig = s.request

    def _req(method, url, **kw):
        kw.setdefault("timeout", 15)
        kw.setdefault("allow_redirects", False)
        return orig(method, url, **kw)

    # Patching s.request alone doesn't work: Session.get/post/etc each set
    # allow_redirects=True in kwargs themselves before calling s.request(),
    # so our setdefault() above never sees a missing key to default. A test
    # calling http.get(...) expecting no-redirect-follow (e.g.
    # test_expired_session_cookie_rejected) would silently chase the app's
    # redirect target instead — found this when that test errored out
    # trying to connect to the Location header's host directly rather than
    # just inspecting the 302 it was supposed to check.
    s.request = _req
    s.get = lambda url, **kw: _req("GET", url, **kw)
    s.post = lambda url, **kw: _req("POST", url, **kw)
    s.patch = lambda url, **kw: _req("PATCH", url, **kw)
    s.put = lambda url, **kw: _req("PUT", url, **kw)
    s.delete = lambda url, **kw: _req("DELETE", url, **kw)
    return s


@pytest.fixture()
def admin_token():
    tok = _env("ADMIN_API_TOKEN")
    if not tok:
        pytest.skip("ADMIN_API_TOKEN not set — configure to enable this test")
    return tok


@pytest.fixture()
def lowpriv_token():
    tok = _env("LOWPRIV_API_TOKEN")
    if not tok:
        pytest.skip("LOWPRIV_API_TOKEN not set — configure to enable this test")
    return tok


@pytest.fixture()
def customer_cookie():
    c = _env("CUSTOMER_COOKIE")
    if not c:
        pytest.skip("CUSTOMER_COOKIE not set — configure to enable this test")
    return c


@pytest.fixture()
def lowpriv_cookie():
    c = _env("LOWPRIV_COOKIE")
    if not c:
        pytest.skip("LOWPRIV_COOKIE not set — configure to enable this test")
    return c


def bearer(token):
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}
