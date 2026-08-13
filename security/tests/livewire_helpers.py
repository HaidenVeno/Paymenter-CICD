"""
Drives Livewire v3 components the way the real frontend does.

Checkout, Upgrade, and Cart are Livewire components — GET-only page routes
whose actual interactivity goes over Livewire's own AJAX update protocol,
not a classic form POST. Tests that used to `requests.post()` a guessed URL
(`/checkout/{id}`, `/services/{id}/upgrade`, `/cart`) were hitting 404s that
happened to satisfy their assertions without exercising anything real — see
docs/allowlist.md. This module replaces that with the real protocol:

  1. GET the page, pull the target component's `wire:snapshot` (HTML-entity
     decoded) and the page's CSRF token out of the HTML.
  2. POST that snapshot to `/paymenter/update` — a custom-named alias for
     Livewire's update route, not the framework default `/livewire/update` —
     with `updates` (new property values, dot-notation for nested keys like
     `configOptions.5`) and a `calls` entry invoking the real Livewire
     action method (e.g. `checkout`, `applyCoupon`, `nextStep`).
"""
import json
import re


def get_component_snapshot(html, name_substr, exact=False):
    """Find the first wire:snapshot whose memo.name contains name_substr (or
    equals it exactly, if exact=True — needed when one component's name is a
    substring of another's, e.g. the page-level "cart" component vs. the
    navbar's "components.cart" widget, which can appear earlier in the HTML),
    HTML-entity-decoded and parsed. Returns the raw (still-encoded) snapshot
    string Livewire expects to receive back, or None if not found."""
    for m in re.finditer(r'wire:snapshot="([^"]*)"', html):
        raw = (
            m.group(1)
            .replace("&quot;", '"')
            .replace("&amp;", "&")
            .replace("&#039;", "'")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
        )
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        name = data.get("memo", {}).get("name", "")
        if (name == name_substr) if exact else (name_substr in name):
            return raw
    return None


def get_csrf_token(html):
    m = re.search(r'name="csrf-token" content="([^"]+)"', html)
    return m.group(1) if m else None


def post_snapshot_update(http, base_url, snapshot, token, method, updates=None, cookie_header=None, params=None):
    """Shared POST /paymenter/update body-building + request, used by both
    livewire_call() (first call, snapshot pulled from a GET) and
    continue_livewire_call() (chained call, snapshot pulled from a prior
    response) so the two entry points can't drift apart."""
    payload = {
        "_token": token,
        "components": [{
            "snapshot": snapshot,
            "updates": updates or {},
            "calls": [{"path": "", "method": method, "params": params or []}],
        }],
    }
    call_headers = {
        "Content-Type": "application/json",
        "X-Livewire": "true",
        "X-CSRF-TOKEN": token,
        "Accept": "application/json",
    }
    if cookie_header:
        call_headers["Cookie"] = cookie_header
    return http.post(
        f"{base_url}/paymenter/update",
        data=json.dumps(payload),
        headers=call_headers,
        allow_redirects=False,
    )


def continue_livewire_call(http, base_url, prior_response, token, method,
                            updates=None, cookie_header=None, params=None, component_index=0):
    """Chain a follow-up Livewire action onto the SAME component instance
    using the snapshot a prior livewire_call()/continue_livewire_call()
    response returned, without re-GETing the page. This is how a real
    Livewire client behaves across a multi-step interaction (apply a coupon,
    then check out, on the same `cart` component) — and it matters for more
    than fidelity: re-GETing between every step re-triggers page-level
    controls like nginx's `/cart` coupon brute-force rate limit
    (limit_req zone=cart, 5r/m burst=2) on every step, which starves a
    same-source-IP test of the request budget it needs to demonstrate the
    underlying app-layer race at all.

    token: the CSRF token from the session's original page load (it's tied
    to the Laravel session, not the page, so it stays valid across calls).
    """
    body = prior_response.json()
    snapshot = body["components"][component_index]["snapshot"]
    return post_snapshot_update(http, base_url, snapshot, token, method,
                         updates=updates, cookie_header=cookie_header, params=params)


def livewire_call(http, base_url, page_url, component_name, method,
                   updates=None, cookie_header=None, params=None, exact_name=False):
    """GET page_url, then invoke `method` on the named component via a real
    Livewire update request. Returns the raw requests.Response from the
    POST to /paymenter/update (the page GET's response is discarded once the
    snapshot/csrf are pulled from it, matching how a browser only cares
    about the AJAX response).

    cookie_header: a full `Cookie:` header value (e.g. "paymenter_session=...").
    Raises AssertionError if the target component isn't found in the page
    (a real signal the page didn't load/render as expected, not silently
    skipped).
    """
    headers = {"Cookie": cookie_header} if cookie_header else {}
    r = http.get(f"{base_url}{page_url}", headers=headers, allow_redirects=True)
    assert r.status_code == 200, (
        f"GET {page_url} returned {r.status_code}, expected 200 — can't "
        f"locate the {component_name} component to test against."
    )
    snapshot = get_component_snapshot(r.text, component_name, exact=exact_name)
    assert snapshot is not None, (
        f"Could not find a wire:snapshot for component '{component_name}' "
        f"on {page_url} — the page structure may have changed."
    )
    token = get_csrf_token(r.text)
    return post_snapshot_update(http, base_url, snapshot, token, method,
                         updates=updates, cookie_header=cookie_header, params=params)
