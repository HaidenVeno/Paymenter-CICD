"""Lab 3 s2.2-s2.3 — config option injection (checkout / upgrade).

Config option values were accepted, stored, and reflected verbatim (XSS, SQLi,
SSTI, path traversal, oversized input) with no content validation. This harness
re-runs the known payloads against the checkout config-option field and asserts
they are not reflected unencoded into the response.

Requires CUSTOMER_COOKIE and a product with a text config option; skips
otherwise. Complements the static analysis — this is the runtime fuzz re-run.
"""
import os
import pytest

PAYLOADS = {
    "xss": "<script>alert(1)</script>",
    "sqli": "'; DROP TABLE users;--",
    "cmdi": "; id",
    "ssti": "{{7*7}}",
    "path": "../../../../etc/passwd",
    "nullbyte": "abc%00def",
}


@pytest.mark.needs_auth
@pytest.mark.parametrize("name,payload", list(PAYLOADS.items()))
def test_checkout_config_option_not_reflected_unencoded(http, base_url, customer_cookie, name, payload):
    product_id = os.environ.get("CHECKOUT_PRODUCT_ID")
    option_field = os.environ.get("CHECKOUT_OPTION_FIELD", "configOptions[text]")
    if not product_id:
        pytest.skip("CHECKOUT_PRODUCT_ID not set — configure to enable this test")

    r = http.post(
        f"{base_url}/checkout/{product_id}",
        headers={"Cookie": customer_cookie},
        data={option_field: payload},
    )
    assert r.status_code < 500, f"[{name}] checkout 500'd on payload: {r.status_code}"
    # The raw XSS/SSTI payload must not appear unescaped in the response body.
    if name in ("xss", "ssti"):
        assert payload not in r.text, (
            f"[{name}] payload reflected verbatim into the response — stored/"
            f"reflected injection (Lab 3 s2.2) is unmitigated."
        )
    if name == "ssti":
        assert "49" not in r.text, "[ssti] template expression evaluated (7*7=49)."
