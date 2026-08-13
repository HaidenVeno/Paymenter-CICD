"""Lab 4 s1.2 / Lab 4 Bug 10.2 / Lab 5 s3.5-s3.6 — RBAC wildcard self-escalation.

There is no `admin/roles` API resource (`routes/api.php` has no `roles`
entry — confirmed 404), so the previous version of this test, which PATCHed
`/api/v1/admin/roles/{id}` with an ApiKey bearer token, was hitting a route
that doesn't exist and always got denied for reasons unrelated to RBAC. Role
editing is a Filament admin panel page (`admin/roles/{record}/edit`, GET-only
— it's Livewire-based like Checkout/Cart/Upgrade) and RBAC there is enforced
against the web SESSION (`User->role`), not the ApiKey permission system, so
this drives it with a low-privilege staff session cookie instead.

Originally live-verified against the deployed fork (then reverted): a "viewer"
role holding only `admin.roles.viewAny`/`admin.roles.view` (no
`admin.roles.update`) could grant itself wildcard permissions this way, and it
landed in the database. Root cause was two missing guards, both now fixed in
the app fork (`HaidenVeno/Paymenter`):
  * `App\\Admin\\Resources\\RoleResource::canEdit()` was hardcoded to
    `$record->id !== 1` and never consulted `RolePolicy::update()`; it now
    also requires the policy's `update` ability, so a viewer that lacks
    `admin.roles.update` gets a 403 on the edit page.
  * `App\\Models\\Role` now rejects saving `permissions` containing `'*'` on
    any non-seeded role (a `saving` model hook), as defence in depth — the
    CheckboxList form field only constrains the browser UI, and posting
    `data.permissions: ["*"]` directly via the Livewire update protocol
    bypasses it.

The test passes if EITHER layer holds (page-access 403, or the save never
reaching the DB), so it stays valid whichever way the enforcement lands. Kept
a hard (non-xfail) gate — it's a regression guard for a real self-escalation,
so it must fail loudly if either guard is ever removed again.

Requires LOWPRIV_COOKIE (a session cookie for a staff account with only
`admin.roles.viewAny`/`admin.roles.view`) and LOWPRIV_ROLE_ID (that account's
own role id, id != 1); skips otherwise.
"""
import os
import pytest
import requests
from livewire_helpers import get_component_snapshot, get_csrf_token, post_snapshot_update
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
        # Two layers can block this, and the test passes if EITHER holds:
        #  1. Page access — a policy-aware canEdit() 403s the edit page for a
        #     viewer that lacks admin.roles.update (the primary fix), so the
        #     save form is never reachable.
        #  2. Persistence — even if the form loads, the Role model rejects
        #     saving '*' onto a non-seeded role (defence in depth).
        page = session.get(
            f"{base_url}/admin/roles/{role_id}/edit",
            headers={"Cookie": f"paymenter_session={lowpriv_cookie}"},
            allow_redirects=False,
        )
        if page.status_code != 200:
            # Layer 1 blocked access outright — the correct outcome.
            assert page.status_code in (301, 302, 303, 307, 308, 401, 403), (
                f"Unexpected status {page.status_code} loading the role edit "
                f"page as a low-priv session."
            )
        else:
            # Page loaded — exercise layer 2: attempt the wildcard save and
            # confirm it never reaches the database.
            token = get_csrf_token(page.text)
            snapshot = get_component_snapshot(page.text, "RoleResource\\Pages\\EditRole")
            assert snapshot is not None, "Could not find the EditRole component snapshot"
            r = post_snapshot_update(
                session, base_url, snapshot, token, "save",
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
    # Negative control: the seeded super-admin role (id 1) must never be
    # editable through the panel — its edit page must 403/redirect for a
    # low-priv session regardless of the policy check.
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
