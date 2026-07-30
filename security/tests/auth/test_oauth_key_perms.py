"""Lab 4 s2.1-s2.2 / Lab 5 s3.1 — OAuth secret & signing-key exposure.

Two assertions as concrete pipeline checks:
  * storage/oauth-private.key must be 660 or stricter (never world-readable/
    writable). Lab 4 found it 777 inside the container.
  * OAuth client-secret settings must not be declared plaintext ('type' =>
    'text') in app/Classes/Settings.php.

Runs via `docker exec` against the live container; skips if docker or the
container is unavailable.
"""
import os
import shutil
import subprocess
import pytest


def _container():
    name = os.environ.get("PAYMENTER_CONTAINER")
    if name:
        return name
    if not shutil.which("docker"):
        return None
    try:
        out = subprocess.run(
            ["docker", "ps", "--filter", "ancestor=paymenter:local", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=15,
        )
        names = [n for n in out.stdout.split() if n]
        return names[0] if names else None
    except Exception:
        return None


@pytest.fixture()
def container():
    c = _container()
    if not c:
        pytest.skip("paymenter container not found / docker unavailable")
    return c


@pytest.mark.needs_docker
def test_oauth_private_key_permissions(container):
    r = subprocess.run(
        ["docker", "exec", container, "stat", "-c", "%a", "/app/storage/oauth-private.key"],
        capture_output=True, text=True, timeout=15,
    )
    if r.returncode != 0:
        pytest.skip(f"oauth-private.key not present yet: {r.stderr.strip()}")
    mode = r.stdout.strip()
    # Expect 600 or 660; reject anything granting world bits or group-write beyond 660.
    assert mode in ("600", "640", "660"), (
        f"oauth-private.key mode is {mode}; expected <= 660 (Lab 5 s3.1)."
    )


@pytest.mark.needs_docker
def test_oauth_client_secrets_not_plaintext(container):
    # Settings.php should not declare oauth_*_client_secret as 'type' => 'text'.
    r = subprocess.run(
        ["docker", "exec", container, "sh", "-c",
         "grep -n -A2 \"oauth_.*_client_secret\" /app/app/Classes/Settings.php || true"],
        capture_output=True, text=True, timeout=15,
    )
    block = r.stdout
    if not block.strip():
        pytest.skip("Could not read Settings.php oauth secret definitions")
    assert "'type' => 'text'" not in block and '"type" => "text"' not in block, (
        "An oauth_*_client_secret is still declared as plaintext 'type' => "
        "'text' (Lab 4 s2.1). It must be 'type' => 'password', 'encrypted' => "
        "true — applied via migration, not a live flag flip (Lab 5 s3.4)."
    )
