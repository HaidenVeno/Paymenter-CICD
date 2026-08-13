"""
SSH-based verification against the actual deploy target (Staging), for
checks that can't be answered from the deployed app's HTTP surface alone
(container file permissions, ground-truth database state after a mass-
assignment attempt). Same DEPLOY_HOST/DEPLOY_USER/DEPLOY_SSH_KEY convention
deploy.yml and config-audit.sh already use — these are workflow-level env
in security-tests.yml, so they're available to every job without extra
wiring.

Deliberately over SSH to the deploy target, not local `docker exec` — the
Runner and Staging are different hosts, so a local-only check silently
never runs anything in CI (this was test_oauth_key_perms.py's exact bug).
"""
import base64
import os
import shutil
import subprocess


def deploy_target_available():
    return bool(
        os.environ.get("DEPLOY_HOST")
        and os.environ.get("DEPLOY_SSH_KEY")
        and shutil.which("ssh")
    )


def remote_exec(cmd, timeout=15):
    """Run `cmd` (a shell string) over SSH on the deploy target. Returns a
    subprocess.CompletedProcess. Returns None if SSH itself couldn't be
    attempted (missing config) rather than raising, so callers can skip
    cleanly."""
    if not deploy_target_available():
        return None
    host = os.environ["DEPLOY_HOST"]
    user = os.environ.get("DEPLOY_USER", "hveno")
    key = os.environ["DEPLOY_SSH_KEY"]
    try:
        return subprocess.run(
            ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=10",
             "-i", key, f"{user}@{host}", cmd],
            capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None


def remote_docker_exec(container, inner_cmd, timeout=15):
    """Run `inner_cmd` inside `container` on the deploy target via SSH +
    docker exec."""
    # Single-quote the inner command defensively; it's always a fixed
    # string we wrote, never attacker input, but keep the boundary clean.
    escaped = inner_cmd.replace("'", "'\\''")
    return remote_exec(f"docker exec {container} sh -c '{escaped}'", timeout=timeout)


def remote_mysql(cid, sql, timeout=15):
    """Run `sql` against the app database inside the `cid` container. SQL
    text (e.g. a JSON permissions array containing embedded double quotes)
    routinely contains characters that collide with shell quoting once
    passed through both the SSH-invoked login shell and `docker exec`'s own
    `sh -c` layer — a value like '["a","b"]' inside a naively double-quoted
    `-e "..."` argument gets its embedded `"` read as the argument's own
    closing quote by one of those shells, silently truncating/mangling the
    statement (hit this for real writing the RBAC wildcard test's cleanup
    step). Base64-encoding the SQL sidesteps the whole problem: the encoded
    text has no shell-meaningful characters at all, so it survives every
    quoting layer unchanged and is decoded only at the very end, inside the
    container.
    """
    encoded = base64.b64encode(sql.encode()).decode()
    inner = (
        f"echo {encoded} | base64 -d | "
        "mariadb -N -u paymenter -p$(cat /run/secrets/db_password) paymenter"
    )
    return remote_docker_exec(cid, inner, timeout=timeout)


def remote_container_id(service, compose_file="docker-compose.yml"):
    """Resolve a running container's ID on the deploy target by compose
    service name (same technique config-audit.sh uses) — more robust than
    hardcoding a container name. PAYMENTER_CONTAINER overrides directly."""
    override = os.environ.get("PAYMENTER_CONTAINER")
    if override:
        return override
    path = os.environ.get("DEPLOY_PATH", "/home/hveno/Paymenter-CICD/docker")
    r = remote_exec(f"docker compose -f '{path}/{compose_file}' ps -q {service}")
    if not r or r.returncode != 0:
        return None
    cid = r.stdout.strip()
    return cid or None
