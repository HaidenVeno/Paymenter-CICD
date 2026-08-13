"""Lab 3 s2.3 / Lab 4 mass-assignment — service upgrade config-option injection.

The fix filters submitted config option IDs against the product's
`upgradableConfigOptions` allowlist. This runtime test complements the blocking
Semgrep rule (paymenter-upgrade-configoption-mass-assignment): it drives the
real `services.upgrade` Livewire component (App\\Livewire\\Services\\Upgrade)
over its actual AJAX update protocol (see livewire_helpers.py — the previous
version of this test POSTed a classic form body to `/services/{id}/upgrade`,
a GET-only route whose real interactivity is Livewire, so it always got a
non-2xx response for reasons that had nothing to do with the allowlist) and
injects a config_option_id outside the product's allowlist.

`doUpgrade()` only validates fields it has declared rules for, so an
undeclared `configOptions.<bogus_id>` key rides along in the request
harmlessly and the component itself never errors — the allowlist fix lives
in the *persistence* loop, which iterates the product's real
upgradableConfigOptions rather than the submitted keys. The admin API doesn't
expose per-service config rows, so the only ground truth is the database
itself: this test queries `service_configs` over SSH on the deploy target
(remote_helpers.py) and asserts no row was ever created for the injected id.

Requires a customer session, a known upgradeable service, and deploy-target
SSH access; skips otherwise.
"""
import os
import pytest
from livewire_helpers import livewire_call
from remote_helpers import deploy_target_available, remote_container_id, remote_mysql


@pytest.mark.needs_auth
def test_upgrade_rejects_unlisted_config_option(http, base_url, customer_cookie):
    service_id = os.environ.get("UPGRADE_SERVICE_ID")
    bogus_option_id = os.environ.get("BOGUS_CONFIG_OPTION_ID", "999999")
    if not service_id:
        pytest.skip("UPGRADE_SERVICE_ID not set — configure to enable this test")
    if not deploy_target_available():
        pytest.skip("DEPLOY_HOST/DEPLOY_SSH_KEY not set — can't verify DB state")

    r = livewire_call(
        http, base_url, f"/services/{service_id}/upgrade", "services.upgrade", "doUpgrade",
        updates={f"configOptions.{bogus_option_id}": "1"},
        cookie_header=f"paymenter_session={customer_cookie}",
    )
    assert r.status_code < 500, f"Upgrade component 500'd on injected option: {r.status_code}"

    cid = remote_container_id("database")
    assert cid, "Could not resolve the database container on the deploy target"

    bogus_id_int = int(bogus_option_id)  # deliberately fail loudly on a non-numeric env var
    result = remote_mysql(
        cid, f"SELECT COUNT(*) FROM service_configs WHERE config_option_id = {bogus_id_int};",
    )
    assert result is not None and result.returncode == 0, (
        f"DB verification query failed: {result.stderr.strip() if result else 'no SSH result'}"
    )
    count = int(result.stdout.strip() or "0")
    assert count == 0, (
        f"Server persisted {count} service_configs row(s) referencing a "
        f"config_option_id outside the product's upgradableConfigOptions "
        f"allowlist — the Lab 3 s2.3 mass-assignment fix has regressed."
    )
