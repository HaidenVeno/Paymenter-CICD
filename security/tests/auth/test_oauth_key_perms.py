"""Lab 4 s2.1-s2.2 / Lab 5 s3.1 — OAuth secret & signing-key exposure.

Two assertions as concrete pipeline checks:
  * storage/oauth-private.key must be 660 or stricter (never world-readable/
    writable). Lab 4 found it 777 inside the container.
  * OAuth client-secret settings must not be declared plaintext ('type' =>
    'text') in app/Classes/Settings.php.

Runs via SSH + `docker exec` against the deploy target (remote_helpers.py) —
the previous version shelled out to a *local* `docker`, which always no-ops
in CI since the GitHub Actions runner and Staging are different hosts (the
container is never found locally, so `needs_docker` skipped it silently on
every real run). Skips if SSH/DB access isn't configured or the container
isn't found.
"""
import pytest
from remote_helpers import deploy_target_available, remote_container_id, remote_docker_exec


@pytest.fixture()
def container():
    if not deploy_target_available():
        pytest.skip("DEPLOY_HOST/DEPLOY_SSH_KEY not set — configure to enable this test")
    cid = remote_container_id("paymenter")
    if not cid:
        pytest.skip("paymenter container not found on the deploy target")
    return cid


@pytest.mark.needs_auth
def test_oauth_private_key_permissions(container):
    r = remote_docker_exec(container, "stat -c %a /app/storage/oauth-private.key")
    if not r or r.returncode != 0:
        pytest.skip(f"oauth-private.key not present yet: {r.stderr.strip() if r else 'no SSH result'}")
    mode = r.stdout.strip()
    # Expect 600 or 660; reject anything granting world bits or group-write beyond 660.
    assert mode in ("600", "640", "660"), (
        f"oauth-private.key mode is {mode}; expected <= 660 (Lab 5 s3.1)."
    )


@pytest.mark.needs_auth
def test_oauth_client_secrets_not_plaintext(container):
    # Settings.php should not declare oauth_*_client_secret as 'type' => 'text'.
    r = remote_docker_exec(
        container,
        'grep -n -A2 "oauth_.*_client_secret" /app/app/Classes/Settings.php || true',
    )
    block = r.stdout if r else ""
    if not block.strip():
        pytest.skip("Could not read Settings.php oauth secret definitions")
    assert "'type' => 'text'" not in block and '"type" => "text"' not in block, (
        "An oauth_*_client_secret is still declared as plaintext 'type' => "
        "'text' (Lab 4 s2.1). It must be 'type' => 'password', 'encrypted' => "
        "true — applied via migration, not a live flag flip (Lab 5 s3.4)."
    )
