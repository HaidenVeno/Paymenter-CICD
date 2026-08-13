"""Lab 3 s2.5 — coupon race condition (concurrent redemption).

Firing concurrent redemptions of a max_uses-capped coupon produced 2x HTTP 200
and 8x HTTP 500 (a Livewire crash), and risks redemption beyond the cap due to
missing row locking. Lab 5 did NOT virtual-patch this — it remains an open,
disclosed finding — so this is tracked as xfail rather than a hard gate. When
the row-locking fix lands, remove the xfail and it becomes a regression guard.

The coupon's use count (`Coupon::validateCoupon()`, App/Classes/Cart.php) is
enforced against `$coupon->services->count()`, which is only incremented when
a distinct account's `Cart::checkout()` actually commits an Order/Service —
applying a coupon to a cart (the old test's target, `POST /cart?coupon=`)
never itself consumes a redemption, so racing that endpoint tested nothing.
This drives the real, vulnerable code path: N distinct customer accounts each
add the seeded product to their own cart and apply the shared coupon (setup,
not timed), then all N accounts' `cart` Livewire components call `checkout()`
concurrently (the timed race) — no row lock guards `coupon->services->count()`
between the check and the commit, so overlapping requests can all pass
validation before any of them persist. Verified via direct DB count
(remote_helpers.py) since the admin API doesn't expose coupon redemption
counts.

A fixed max_uses would only prove anything on a coupon's first-ever run — every
CI run permanently adds real Service rows to whichever coupon is shared here,
so a wide max_uses (e.g. 50) leaves huge headroom that N=2 racers can never
exhaust, and the test would silently "pass" without actually stressing the
race window at all. Instead, right before racing, this pins the coupon's
max_uses (over SSH DB write — a dedicated RACE_COUPON_CODE coupon, never a
real one) to exactly `current_use_count + RACE_COUPON_SLOTS` (default 1
legitimate slot) — guaranteeing a tight race window on every run regardless
of how much prior runs have already consumed, so the test stays meaningful
indefinitely rather than degrading after the coupon "fills up" once.

Requires RACE_CUSTOMER_COOKIES (comma-separated session cookies for >= 2
distinct customer accounts), RACE_COUPON_CODE, CHECKOUT_CATEGORY_SLUG,
CHECKOUT_PRODUCT_SLUG, CHECKOUT_CONFIG_OPTION_ID, and CHECKOUT_PLAN_ID; skips
otherwise. RACE_COUPON_SLOTS is optional (default 1).
"""
import concurrent.futures
import os
import pytest
import requests
from livewire_helpers import (
    post_snapshot_update,
    continue_livewire_call,
    get_component_snapshot,
    get_csrf_token,
    livewire_call,
)
from remote_helpers import deploy_target_available, remote_container_id, remote_mysql


def _setup_cart(session, base_url, cookie, category_slug, product_slug, plan_id, option_id, coupon_code):
    """Add the seeded product to this account's cart, then GET /cart exactly
    ONCE and apply the shared coupon by chaining off that single snapshot.
    Returns (combined_cookie_header, post_coupon_response, csrf_token) so
    the race step can chain checkout() off the coupon-application response
    too — never re-GETing /cart. That GET is covered by nginx's `/cart`
    coupon brute-force rate limit (5r/m burst=2), and every racer sharing
    this test's one source IP would otherwise exhaust that tiny budget
    before the concurrent checkout calls even fire.
    """
    r = livewire_call(
        session, base_url, f"/products/{category_slug}/{product_slug}/checkout?plan={plan_id}",
        "products.checkout", "checkout",
        updates={f"configOptions.{option_id}": "race-test", "plan_id": plan_id},
        cookie_header=f"paymenter_session={cookie}",
    )
    assert r.status_code == 200, f"add-to-cart failed for this account: {r.status_code}"
    cart_cookie = session.cookies.get("cart")
    assert cart_cookie, "no cart cookie set after adding the product to cart"
    full_cookie = f"paymenter_session={cookie}; cart={cart_cookie}"

    page = session.get(f"{base_url}/cart", headers={"Cookie": full_cookie})
    assert page.status_code == 200, f"GET /cart failed for this account: {page.status_code}"
    token = get_csrf_token(page.text)
    snapshot = get_component_snapshot(page.text, "cart", exact=True)
    assert snapshot is not None, "Could not find the cart component's wire:snapshot on /cart"

    r2 = post_snapshot_update(
        session, base_url, snapshot, token, "applyCoupon",
        updates={"coupon": coupon_code}, cookie_header=full_cookie,
    )
    assert r2.status_code == 200, f"apply-coupon failed for this account: {r2.status_code}"
    return full_cookie, r2, token


def _coupon_use_count(cid, coupon_code):
    result = remote_mysql(
        cid,
        "SELECT COUNT(*) FROM services WHERE coupon_id = "
        f"(SELECT id FROM coupons WHERE code = '{coupon_code}');",
    )
    assert result is not None and result.returncode == 0, (
        f"DB verification query failed: {result.stderr.strip() if result else 'no SSH result'}"
    )
    return int(result.stdout.strip() or "0")


def _pin_coupon_max_uses(cid, coupon_code, value):
    """Set the coupon's real max_uses column directly (SSH DB write) so the
    race always starts with exactly `value` legitimate slots left, no matter
    how many prior CI runs already redeemed it. Restricted to the dedicated
    RACE_COUPON_CODE test fixture, never invoked against a real coupon."""
    result = remote_mysql(
        cid, f"UPDATE coupons SET max_uses = {int(value)} WHERE code = '{coupon_code}';",
    )
    assert result is not None and result.returncode == 0, (
        f"Failed to pin coupon max_uses: {result.stderr.strip() if result else 'no SSH result'}"
    )


@pytest.mark.open_finding
@pytest.mark.needs_auth
@pytest.mark.xfail(reason="Lab 3 s2.5 disclosed, not yet patched (no row locking)", strict=False)
def test_concurrent_coupon_checkout_no_500_and_no_overuse(base_url):
    cookies_raw = os.environ.get("RACE_CUSTOMER_COOKIES")
    coupon_code = os.environ.get("RACE_COUPON_CODE")
    slots = int(os.environ.get("RACE_COUPON_SLOTS", "1"))
    category_slug = os.environ.get("CHECKOUT_CATEGORY_SLUG")
    product_slug = os.environ.get("CHECKOUT_PRODUCT_SLUG")
    option_id = os.environ.get("CHECKOUT_CONFIG_OPTION_ID")
    plan_id = os.environ.get("CHECKOUT_PLAN_ID")
    if not (cookies_raw and coupon_code and category_slug and product_slug and option_id and plan_id):
        pytest.skip(
            "RACE_CUSTOMER_COOKIES/RACE_COUPON_CODE/CHECKOUT_CATEGORY_SLUG/"
            "CHECKOUT_PRODUCT_SLUG/CHECKOUT_CONFIG_OPTION_ID/CHECKOUT_PLAN_ID "
            "not set — configure to enable this test"
        )
    if not deploy_target_available():
        pytest.skip("DEPLOY_HOST/DEPLOY_SSH_KEY not set — can't verify DB state")

    cookies = [c.strip() for c in cookies_raw.split(",") if c.strip()]
    assert len(cookies) >= 2, (
        "RACE_CUSTOMER_COOKIES needs >= 2 distinct account cookies to "
        "demonstrate a cross-account race (a single cart can't over-redeem "
        "itself — checkout empties it after the first success)."
    )

    cid = remote_container_id("database")
    assert cid, "Could not resolve the database container on the deploy target"

    initial = _coupon_use_count(cid, coupon_code)
    _pin_coupon_max_uses(cid, coupon_code, initial + slots)

    sessions = [requests.Session() for _ in cookies]
    for s in sessions:
        s.verify = False
    setups = [
        _setup_cart(sessions[i], base_url, cookies[i], category_slug, product_slug,
                    plan_id, option_id, coupon_code)
        for i in range(len(cookies))
    ]

    def race(i):
        full_cookie, coupon_response, token = setups[i]
        return continue_livewire_call(
            sessions[i], base_url, coupon_response, token, "checkout",
            cookie_header=full_cookie,
        ).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(cookies)) as ex:
        results = list(ex.map(race, range(len(cookies))))

    assert 500 not in results, f"Concurrent checkout produced HTTP 500 (crash): {results}."

    final = _coupon_use_count(cid, coupon_code)
    gained = final - initial
    assert gained <= slots, (
        f"Concurrent checkout redeemed the coupon {gained} more time(s) across "
        f"{len(cookies)} accounts (use count {initial} -> {final}), exceeding "
        f"the {slots} legitimate slot(s) pinned for this race — missing row "
        f"locking (Lab 3 s2.5) allows over-redemption."
    )
