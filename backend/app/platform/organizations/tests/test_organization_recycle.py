import os

os.environ.setdefault("SECRET_KEY", "Organization-Recycle-Test-2026!safe")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.database.soft_delete import SoftDeleteBase
from app.core.models.data_lifecycle import LifecycleAuditEvent, RecycleBinItem
from app.core.models.identity import Organization, OrganizationMember, User
from app.core.models.project import Project, ProjectMember
from app.lifecycle.service import batch_restore
from app.platform.organizations.services.management_service import (
    delete_organization, preview_organization_delete,
)


@event.listens_for(Session, "do_orm_execute")
def _filter_soft_deleted(execute_state):
    if execute_state.is_select and not execute_state.execution_options.get("include_deleted", False):
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(SoftDeleteBase, lambda model: model.deleted_at.is_(None), include_aliases=True),
        )


def _database():
    engine = create_engine("sqlite://")
    for table in [
        User.__table__, Organization.__table__, OrganizationMember.__table__, Project.__table__,
        ProjectMember.__table__, RecycleBinItem.__table__, LifecycleAuditEvent.__table__,
    ]:
        table.create(engine, checkfirst=True)
    return engine


def test_organization_delete_unlinks_members_and_restore_keeps_accounts():
    engine = _database()
    with Session(engine) as db:
        admin = User(username="platform-admin", role="admin")
        member_user = User(username="retained-user", role="dev")
        db.add_all([admin, member_user])
        db.flush()
        organization = Organization(name="Joey 的组织", owner_id=admin.id)
        db.add(organization)
        db.flush()
        member = OrganizationMember(
            organization_id=organization.id, user_id=member_user.id, role="member",
            agent_enabled=False, allowed_model_ids=[],
        )
        db.add(member)
        db.commit()

        preview = preview_organization_delete(organization.id, db, admin)
        assert preview.name == "Joey 的组织"
        assert (preview.member_count, preview.project_count) == (1, 0)
        result = delete_organization(organization.id, db, admin)
        assert db.query(Organization).filter_by(id=organization.id).first() is None
        assert db.query(OrganizationMember).filter_by(id=member.id).first() is None
        assert db.get(User, member_user.id).is_active is True

        items = db.query(RecycleBinItem).filter(
            RecycleBinItem.deletion_batch_id == result.deletion_batch_id,
        ).all()
        assert {item.resource_type for item in items} == {"organization", "organization_member"}
        restored = batch_restore(db, [item.id for item in items], admin)
        assert restored["failed"] == 0, restored
        assert db.query(Organization).filter_by(id=organization.id).first() is not None
        assert db.query(OrganizationMember).filter_by(id=member.id).first() is not None
        assert db.get(User, member_user.id).is_active is True
    engine.dispose()


def test_organization_delete_preview_and_operation_preserve_associated_projects():
    engine = _database()
    with Session(engine) as db:
        admin = User(username="project-admin", role="admin")
        db.add(admin)
        db.flush()
        organization = Organization(name="Org with project", owner_id=admin.id)
        db.add(organization)
        db.flush()
        project = Project(name="linked project", owner_id=admin.id, organization_id=organization.id)
        db.add(project)
        db.commit()

        preview = preview_organization_delete(organization.id, db, admin)
        assert preview.project_count == 1
        assert preview.projects[0].name == "linked project"
        from fastapi import HTTPException
        import pytest

        with pytest.raises(HTTPException) as error:
            delete_organization(organization.id, db, admin)
        assert error.value.status_code == 409
        assert db.get(Organization, organization.id).deleted_at is None
        assert db.get(Project, project.id).deleted_at is None
    engine.dispose()
