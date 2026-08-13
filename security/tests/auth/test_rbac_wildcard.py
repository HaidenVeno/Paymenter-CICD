"""Lab 4 s1.2 / Lab 4 Bug 10.2 / Lab 5 s3.5-s3.6 — RBAC wildcard self-escalation.

There is no `admin/roles` API resource (`routes/api.php` has no `roles`
entry — confirmed 404), so the previous version of this test, which PATCHed
`/api/v1/admin/roles/{id}` with an ApiKey bearer token, was hitting a route
that doesn't exist and always got denied for reasons unrelated to RBAC. Role
editing is a Filament admin panel page (`admin/roles/{record}/edit`, GET-only
— it's Livewire-based like Checkout/Cart/Upgrade) and RBAC there is enforced
against the web SESSION (`User->role`), not the ApiKey permission system, so
this drives it with a low-privilege staff session cookie instead.

Live-verified against the deployed app fork (then reverted): a "viewer" role
holding only `admin.roles.viewAny`/`admin.roles.view` (no `admin.roles.update`)
CAN currently grant itself wildcard permissions this way, and it lands in the
database. Root cause, from reading the app source:
  * `App\\Admin\\Resources\\RoleResource::canEdit()` is hardcoded to
    `$record->id !== 1` — it never consults `RolePolicy::update()` (which
    does check `admin.roles.update`), so any user who can reach the Roles
    resource can edit any role except the seeded id=1.
  * `App\\Models\\Role` has no save-time guard rejecting `permissions` that
    contain `'*'` for a non-seeded role. The CheckboxList form field only
    constrains the browser UI; posting `data.permissions: ["*"]` directly via
    the Livewire update protocol bypasses it entirely.

This contradicts what this test previously assumed was fixed (s3.5/s3.6) —
that fix either regressed or was never applied to this fork. Left as a hard
(non-xfail) gate, same treatment as test_remember_mfa_bypass.py, since it's a
live, currently-exploitable full-admin self-escalation, not a disclosed/
accepted-risk finding.

Requires LOWPRIV_COOKIE (a session cookie for a staff account with only
`admin.roles.viewAny`/`admin.roles.view`) and LOWPRIV_ROLE_ID (that account's
own role id, id != 1); skips otherwise.
"""
import os
import pytest
import requests
from livewire_helpers import livewire_call
from remote_helpers import deploy_target_available, remote_container_id, remote_mysql


def _role_permissions(cid, role_id):
    result = remote_mysql(cid, f"SELECT permissions FROM roles WHERE id = {int(role_id)};")
    assert result is not None and result.returncode == 0, (
        f"DB verification query failed: {result.stderr.strip() if result else 'no SSH result'}"
    )
    return result.stdout.strip()


@pytest.mark.needs_auth
def test_lowpriv_cannot_self_escalate_via_wildcard(base_url, lowpriv_cookie):
    role_id = os.environ.get("LOWPRIV_ROLE_ID")
    if not role_id:
        pytest.skip("LOWPRIV_ROLE_ID not set — configure to enable this test")
    if not deploy_target_available():
        pytest.skip("DEPLOY_HOST/DEPLOY_SSH_KEY not set — can't verify DB state")

    cid = remote_container_id("database")
    assert cid, "Could not resolve the database container on the deploy target"

    before = _role_permissions(cid, role_id)
    session = requests.Session()
    session.verify = False
    try:
        r = livewire_call(
            session, base_url, f"/admin/roles/{role_id}/edit",
            "RoleResource\\Pages\\EditRole", "save",
            updates={"data.permissions": ["*"]},
            cookie_header=f"paymenter_session={lowpriv_cookie}",
        )
        assert r.status_code < 500, f"Role edit save 500'd: {r.status_code}"

        after = _role_permissions(cid, role_id)
        assert "*" not in after, (
            f"Low-privilege session (role {role_id}, only viewAny/view "
            f"permissions) was able to write wildcard '*' permissions to its "
            f"own role via the Filament edit form (permissions before="
            f"{before!r}, after={after!r}). RBAC self-escalation (Lab 4 "
            f"s1.2 / 10.2, Lab 5 s3.5-s3.6) is unmitigated — canEdit() must "
            f"route through RolePolicy::update() and/or the Role model must "
            f"reject '*' for non-seeded roles."
        )
    finally:
        # Always restore, regardless of pass/fail, so a real vulnerability
        # doesn't leave a live account escalated after the test run.
        if before:
            restore = remote_mysql(
                cid, f"UPDATE roles SET permissions = '{before}' WHERE id = {int(role_id)};"
            )
            assert restore is not None and restore.returncode == 0, (
                f"Failed to restore role {role_id}'s permissions after the test "
                f"— it may still be escalated. Restore manually: "
                f"UPDATE roles SET permissions = '{before}' WHERE id = {role_id}; "
                f"(error: {restore.stderr.strip() if restore else 'no SSH result'})"
            )


@pytest.mark.needs_auth
def test_seeded_admin_role_is_protected(base_url, lowpriv_cookie):
    # Negative control: canEdit()'s one real guard — role id 1 — must still
    # block access to the edit page itself (redirect/403), even though the
    # rest of this file demonstrates that guard is the *only* one in effect.
    session = requests.Session()
    session.verify = False
    resp = session.get(
        f"{base_url}/admin/roles/1/edit",
        headers={"Cookie": f"paymenter_session={lowpriv_cookie}"},
        allow_redirects=False,
    )
    assert resp.status_code != 200, (
        f"Seeded admin role (id 1) edit page was reachable by a low-priv "
        f"session (status {resp.status_code})."
    )
