"""Lab 3 s6.3 / Lab 4 s1.8 / Lab 5 s2.3 — admin API rate limiting.

Virtual patch 2 applies a 60 req/min (burst 5) edge limiter to /api/v1/admin/*,
matching the throttle already present on /oauth/token. A sustained burst must
produce at least one HTTP 429. Enforced at the edge, so no token is required —
unauthenticated requests still traverse the limiter.
"""
import pytest
from conftest import ADMIN_API


@pytest.mark.edge
def test_admin_api_throttles_burst(http, base_url):
    statuses = []
    # 80 rapid requests > 60/min + burst 5 -> limiter must trip.
    for _ in range(80):
        r = http.get(f"{base_url}{ADMIN_API}/services")
        statuses.append(r.status_code)
        if r.status_code == 429:
            break
    assert 429 in statuses, (
        "No HTTP 429 across an 80-request burst to the admin API — the rate "
        "limiter (virtual patch 2) is not active. Lab 4 measured 300/300 = 200 "
        "with zero throttling before this patch."
    )
