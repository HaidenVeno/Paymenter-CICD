"""Lab 3 s2.5 — coupon race condition (concurrent redemption).

Firing concurrent redemptions of a max_uses-capped coupon produced 2x HTTP 200
and 8x HTTP 500 (a Livewire crash), and risks redemption beyond the cap due to
missing row locking. Lab 5 did NOT virtual-patch this — it remains an open,
disclosed finding — so this is tracked as xfail rather than a hard gate. When
the row-locking fix lands, remove the xfail and it becomes a regression guard.

Requires CUSTOMER_COOKIE and a seeded coupon; skips otherwise.
"""
import os
import concurrent.futures
import pytest


@pytest.mark.open_finding
@pytest.mark.needs_auth
@pytest.mark.xfail(reason="Lab 3 s2.5 disclosed, not yet patched (no row locking)", strict=False)
def test_concurrent_coupon_redemption_no_500_and_no_overuse(http, base_url, customer_cookie):
    coupon = os.environ.get("RACE_COUPON_CODE")
    max_uses = int(os.environ.get("RACE_COUPON_MAX_USES", "2"))
    if not coupon:
        pytest.skip("RACE_COUPON_CODE not set — configure to enable this test")

    def apply():
        return http.post(
            f"{base_url}/cart",
            params={"coupon": coupon},
            headers={"Cookie": customer_cookie, "Accept": "application/json"},
        ).status_code

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(lambda _: apply(), range(10)))

    assert 500 not in results, (
        f"Concurrent coupon redemption produced HTTP 500 (crash): {results}. "
        f"Row locking is missing (Lab 3 s2.5)."
    )
    assert results.count(200) <= max_uses, (
        f"Coupon redeemed {results.count(200)} times, exceeding max_uses="
        f"{max_uses} — race allows over-redemption."
    )
