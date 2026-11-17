"""组织与平台管理员权限边界单测。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.models.identity import Organization, OrganizationMember, User
from app.platform.organizations.schemas import MemberGrant, OrganizationUpdate
from app.platform.organizations.services import management_service


def _sqlite_session() -> Session:
    engine = create_engine("sqlite://")
    for table in (User.__table__, Organization.__table__, OrganizationMember.__table__):
        table.create(engine, checkfirst=True)
    return Session(engine)


@pytest.mark.parametrize("role", ["test", "dev"])
@pytest.mark.parametrize(
    "operation",
    [
        lambda user: management_service.preview_organization_delete(1, None, user),
        lambda user: management_service.delete_organization(1, None, user),
    ],
)
def test_non_platform_admin_cannot_delete_organizations(role, operation):
    """组织移入回收站属于平台级治理操作，仅平台管理员可执行。"""
    user = SimpleNamespace(id=7, username="member", role=role)

    with pytest.raises(HTTPException) as error:
        operation(user)

    assert error.value.status_code == 403


def test_organization_admin_boundary_enforced_per_organization():
    """组织管理员只能管理授权组织；普通成员 403，跨组织非成员 404。"""
    with _sqlite_session() as db:
        owner_a = User(username="owner-a", role="test")
        admin_a = User(username="admin-a", role="dev")
        member_a = User(username="member-a", role="test")
        outsider = User(username="outsider", role="test")
        db.add_all([owner_a, admin_a, member_a, outsider])
        db.flush()

        org_a = Organization(name="Org A", owner_id=owner_a.id)
        db.add(org_a)
        db.flush()
        db.add_all([
            OrganizationMember(organization_id=org_a.id, user_id=owner_a.id, role="owner"),
            OrganizationMember(organization_id=org_a.id, user_id=admin_a.id, role="admin"),
            OrganizationMember(organization_id=org_a.id, user_id=member_a.id, role="member"),
        ])
        db.commit()

        # 授权的组织管理员可以管理本组织（改名、查候选、加成员）
        renamed = management_service.update_organization(
            org_a.id, OrganizationUpdate(name="Org A Updated"), db, admin_a
        )
        assert renamed.name == "Org A Updated"
        candidates = management_service.list_candidates(org_a.id, db, admin_a, keyword="outsider")
        assert candidates.total == 1

        # 同组织普通成员 403
        for call in (
            lambda: management_service.update_organization(org_a.id, OrganizationUpdate(name="XX"), db, member_a),
            lambda: management_service.list_candidates(org_a.id, db, member_a),
            lambda: management_service.put_member(
                org_a.id, outsider.id, MemberGrant(user_id=outsider.id, role="member"), db, member_a
            ),
            lambda: management_service.delete_member(org_a.id, admin_a.id, db, member_a),
            lambda: management_service.transfer_ownership(org_a.id, admin_a.id, db, member_a),
        ):
            with pytest.raises(HTTPException) as exc:
                call()
            assert exc.value.status_code == 403

        # 跨组织非成员一律 404，不泄露组织存在性
        for call in (
            lambda: management_service.update_organization(org_a.id, OrganizationUpdate(name="YY"), db, outsider),
            lambda: management_service.list_candidates(org_a.id, db, outsider),
            lambda: management_service.put_member(
                org_a.id, outsider.id, MemberGrant(user_id=outsider.id, role="member"), db, outsider
            ),
            lambda: management_service.delete_member(org_a.id, member_a.id, db, outsider),
            lambda: management_service.transfer_ownership(org_a.id, outsider.id, db, outsider),
        ):
            with pytest.raises(HTTPException) as exc:
                call()
            assert exc.value.status_code == 404


def test_platform_admin_passes_organization_management_guard():
    management_service._require_platform_admin(SimpleNamespace(role="admin"))
