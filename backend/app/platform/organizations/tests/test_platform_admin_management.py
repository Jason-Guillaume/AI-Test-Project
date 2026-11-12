from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.platform.organizations.services import management_service


@pytest.mark.parametrize("role", ["test", "dev"])
@pytest.mark.parametrize(
    "operation",
    [
        lambda user: management_service.create_organization(SimpleNamespace(name="Org"), None, user),
        lambda user: management_service.preview_organization_delete(1, None, user),
        lambda user: management_service.delete_organization(1, None, user),
        lambda user: management_service.update_organization(1, None, None, user),
        lambda user: management_service.find_candidate(1, "person", None, user),
        lambda user: management_service.list_candidates(1, None, user),
        lambda user: management_service.available_models(1, None, user),
        lambda user: management_service.put_member(1, 1, SimpleNamespace(user_id=1), None, user),
        lambda user: management_service.delete_member(1, 1, None, user),
        lambda user: management_service.transfer_ownership(1, 1, None, user),
    ],
)
def test_non_platform_admin_cannot_manage_organizations(role, operation):
    user = SimpleNamespace(id=7, username="member", role=role)

    with pytest.raises(HTTPException) as error:
        operation(user)

    assert error.value.status_code == 403


def test_platform_admin_passes_organization_management_guard():
    management_service._require_platform_admin(SimpleNamespace(role="admin"))
