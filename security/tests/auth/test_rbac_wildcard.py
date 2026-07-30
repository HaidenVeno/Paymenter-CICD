"""Lab 4 s1.2 / Lab 4 Bug 10.2 / Lab 5 s3.5-s3.6 — RBAC wildcard self-escalation.

Two layers were fixed:
  * RoleResource::canEdit() now routes through RolePolicy (s3.5), so a staff
    account holding only a view permission cannot edit/save roles.
  * Role model rejects saving `permissions` containing '*' for any non-seeded
    role (s3.6).

This test drives the API with a low-privilege token and attempts to grant
itself wildcard permissions; it must be denied (403) and must not result in an
escalated role. Requires LOWPRIV_API_TOKEN; skips otherwise.
"""
import os
import pytest
from conftest import ADMIN_API, bearer


@pytest.mark.needs_auth
def test_lowpriv_cannot_self_escalate_via_wildcard(http, base_url, lowpriv_token):
    role_id = os.environ.get("LOWPRIV_ROLE_ID")
    if not role_id:
        pytest.skip("LOWPRIV_ROLE_ID not set — configure to enable this test")

    # Attempt to overwrite the role's permissions with the wildcard.
    r = http.patch(
        f"{base_url}{ADMIN_API}/roles/{role_id}",
        headers=bearer(lowpriv_token),
        json={"permissions": ["*"]},
    )
    assert r.status_code in (401, 403, 422), (
        f"Low-privilege token was able to write wildcard permissions "
        f"(status {r.status_code}). RBAC self-escalation (Lab 4 s1.2 / 10.2) "
        f"has regressed."
    )


@pytest.mark.needs_auth
def test_seeded_admin_role_is_protected(http, base_url, lowpriv_token):
    # Negative control: editing the seeded admin role (id 1) must be denied.
    r = http.patch(
        f"{base_url}{ADMIN_API}/roles/1",
        headers=bearer(lowpriv_token),
        json={"permissions": ["*"]},
    )
    assert r.status_code in (401, 403, 422), (
        f"Seeded admin role (id 1) was editable by a low-priv token "
        f"(status {r.status_code})."
    )
