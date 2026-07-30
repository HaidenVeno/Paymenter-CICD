"""Lab 3 s6.8 / Lab 4 10.1 / Lab 5 s2.2 — `?include=` permission bypass.

Virtual patch 1 blocks any `include` query parameter on admin API paths at the
edge with HTTP 400, regardless of app-layer permission state. This is enforced
before auth, so no token is required to assert it.
"""
import pytest
from conftest import ADMIN_API


@pytest.mark.edge
@pytest.mark.parametrize("include_value", ["user", "invoices", "user,invoices"])
def test_include_param_blocked_on_admin_api(http, base_url, include_value):
    r = http.get(f"{base_url}{ADMIN_API}/services", params={"include": include_value})
    assert r.status_code == 400, (
        f"Expected edge to block ?include={include_value} with 400 "
        f"(virtual patch 1); got {r.status_code}. The permission-bypass "
        f"mitigation has regressed."
    )


@pytest.mark.edge
def test_admin_api_without_include_is_not_blocked(http, base_url):
    # Sanity: the block is scoped to the include parameter, not the whole path.
    # Without a token this should be 401/403 (auth), never the 400 include-block.
    r = http.get(f"{base_url}{ADMIN_API}/services")
    assert r.status_code != 400, (
        "Admin API without ?include returned 400 — the include block is "
        "over-broad and catching unrelated requests."
    )
