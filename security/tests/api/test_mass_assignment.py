"""Lab 3 s2.3 / Lab 4 mass-assignment — service upgrade config-option injection.

The fix filters submitted config option IDs against the product's
`upgradableConfigOptions` allowlist. This runtime test complements the blocking
Semgrep rule (paymenter-upgrade-configoption-mass-assignment): it attempts to
persist a config_option_id that is NOT valid for the product and asserts the
server rejects it rather than mass-assigning it.

Requires a customer session and a known upgradeable service; skips otherwise.
"""
import os
import pytest


@pytest.mark.needs_auth
def test_upgrade_rejects_unlisted_config_option(http, base_url, customer_cookie):
    service_id = os.environ.get("UPGRADE_SERVICE_ID")
    bogus_option_id = os.environ.get("BOGUS_CONFIG_OPTION_ID", "999999")
    if not service_id:
        pytest.skip("UPGRADE_SERVICE_ID not set — configure to enable this test")

    # Attempt to submit a config option ID outside the product's allowlist.
    r = http.post(
        f"{base_url}/services/{service_id}/upgrade",
        headers={"Cookie": customer_cookie, "Accept": "application/json"},
        data={"configOptions[" + bogus_option_id + "]": "1"},
    )
    # The allowlist fix should refuse/ignore the injected option: anything but a
    # clean 2xx acceptance of the bogus write. A 5xx would itself be a defect.
    assert r.status_code < 500, f"Upgrade endpoint 500'd on injected option: {r.status_code}"
    assert r.status_code not in (200, 201, 302), (
        "Server accepted an upgrade referencing a config_option_id outside the "
        "product allowlist — the Lab 3 s2.3 mass-assignment fix has regressed."
    )
