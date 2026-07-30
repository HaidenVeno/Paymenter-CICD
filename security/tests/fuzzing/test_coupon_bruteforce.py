"""Lab 4 Bug 10.3 / Lab 5 s2.4 — coupon brute-force via URL parameter.

The `GET /cart?coupon=CODE` path bypassed the Apply-button rate limiter. Virtual
patch 3 applies a 5 req/min (burst 2) edge limiter to /cart, so a guessing loop
trips 429 within the first several requests. Edge-enforced; no auth required.
"""
import pytest


@pytest.mark.edge
def test_cart_coupon_param_is_rate_limited(http, base_url):
    statuses = []
    for i in range(12):
        r = http.get(f"{base_url}/cart", params={"coupon": f"GUESS{i:04d}"})
        statuses.append(r.status_code)
        if r.status_code == 429:
            break
    assert 429 in statuses, (
        "No HTTP 429 across a 12-request coupon-guessing burst on /cart — "
        "virtual patch 3 is not active. Lab 4 brute-forced a valid coupon "
        "within 50 unthrottled requests before this patch."
    )
    # The limiter should trip quickly (5/min + burst 2).
    assert statuses.index(429) <= 8, (
        f"Rate limit tripped later than expected (at request "
        f"{statuses.index(429) + 1}); check the /cart limit_req config."
    )
