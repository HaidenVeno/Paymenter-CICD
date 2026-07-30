"""Lab 4 s6.1 / Lab 5 s2.5 + s5.1 — CORS wildcard scoping.

Virtual patch 4 strips Paymenter's default `Access-Control-Allow-Origin: *` and
substitutes a scoped trusted origin. Lab 5 s5.1 found the wildcard was NOT
limited to /api/soap/?wsdl=1 — it originated from Paymenter's default behavior
on arbitrary paths — so the fix (and this test) applies to multiple paths.

Also guards the nginx add_header non-merge gotcha (Lab 5 s5.1): a location that
sets its own header must still carry the inherited security headers.
"""
import pytest

PATHS = ["/api/soap/?wsdl=1", "/", "/login"]
EVIL_ORIGIN = "https://evil.example"


@pytest.mark.edge
@pytest.mark.parametrize("path", PATHS)
def test_acao_is_not_wildcard(http, base_url, path):
    r = http.get(f"{base_url}{path}", headers={"Origin": EVIL_ORIGIN})
    acao = r.headers.get("Access-Control-Allow-Origin")
    assert acao != "*", f"{path} returned ACAO '*' — CORS scoping regressed."
    assert acao != EVIL_ORIGIN, (
        f"{path} reflected an untrusted Origin back in ACAO ('{acao}')."
    )


@pytest.mark.edge
@pytest.mark.parametrize("path", PATHS)
def test_security_headers_present_everywhere(http, base_url, path):
    # The CORS-rewriting location must not drop inherited security headers
    # (add_header does not merge across nesting levels).
    r = http.get(f"{base_url}{path}", headers={"Origin": EVIL_ORIGIN})
    assert r.headers.get("X-Content-Type-Options") == "nosniff", (
        f"{path} is missing X-Content-Type-Options — a location-level "
        f"add_header likely dropped inherited security headers."
    )
    assert "X-Frame-Options" in r.headers, f"{path} missing X-Frame-Options."
