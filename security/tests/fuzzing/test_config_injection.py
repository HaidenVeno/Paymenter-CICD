"""Lab 3 s2.2-s2.3 — config option injection (checkout).

Config option values were accepted, stored, and reflected verbatim (XSS, SQLi,
SSTI, path traversal, oversized input) with no content validation. This
harness re-runs the known payloads against the checkout config-option field
and asserts they aren't reflected unencoded into the rendered component HTML.

Drives the real Checkout Livewire component over its actual AJAX update
protocol (see livewire_helpers.py) — the previous version of this test
POSTed to a guessed flat `/checkout/{id}` URL that doesn't exist (the real
route is nested under category/product slugs and is GET-only; interactivity
goes through Livewire, not a form POST), so it always 404'd in a way that
happened to satisfy its old assertions without testing anything.

Requires CUSTOMER_COOKIE, CHECKOUT_CATEGORY_SLUG, CHECKOUT_PRODUCT_SLUG, and
CHECKOUT_CONFIG_OPTION_ID (a text-type config option on that product);
skips otherwise. Complements the static analysis — this is the runtime
fuzz re-run.
"""
import os
import pytest
from livewire_helpers import livewire_call

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
    category_slug = os.environ.get("CHECKOUT_CATEGORY_SLUG")
    product_slug = os.environ.get("CHECKOUT_PRODUCT_SLUG")
    option_id = os.environ.get("CHECKOUT_CONFIG_OPTION_ID")
    if not (category_slug and product_slug and option_id):
        pytest.skip(
            "CHECKOUT_CATEGORY_SLUG/CHECKOUT_PRODUCT_SLUG/"
            "CHECKOUT_CONFIG_OPTION_ID not set — configure to enable this test"
        )

    page_url = f"/products/{category_slug}/{product_slug}/checkout"
    r = livewire_call(
        http, base_url, page_url, "products.checkout", "$refresh",
        updates={f"configOptions.{option_id}": payload},
        cookie_header=f"paymenter_session={customer_cookie}",
    )
    assert r.status_code < 500, f"[{name}] checkout component 500'd on payload: {r.status_code}"

    # The *rendered HTML fragment* is what matters for XSS/SSTI — Livewire's
    # own state snapshot JSON necessarily echoes back whatever you submitted
    # (that's just client-hydration serialization, safely JSON-escaped, not
    # itself a vulnerability), so check the html effect specifically rather
    # than the raw response body.
    try:
        html = r.json()["components"][0]["effects"].get("html", "")
    except (ValueError, KeyError, IndexError):
        html = r.text  # fall back to the raw body if the shape is unexpected

    if name in ("xss", "ssti"):
        assert payload not in html, (
            f"[{name}] payload reflected verbatim into the rendered component "
            f"HTML — stored/reflected injection (Lab 3 s2.2) is unmitigated."
        )
    if name == "ssti":
        assert ">49<" not in html and "\\u003e49\\u003c" not in html, (
            "[ssti] template expression evaluated (7*7=49)."
        )
