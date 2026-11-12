import os

os.environ.setdefault("SECRET_KEY", "Module-Recycle-Test-2026!safe-key")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.database.base import Base
from app.core.database.soft_delete import SoftDeleteBase
from app.core.models.data_lifecycle import LifecycleAuditEvent, RecycleBinItem
from app.core.models.identity import Organization, OrganizationMember, User
from app.core.models.project import Project, ProjectMember
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_module import ApiModule
from app.features.api_catalog.models.api_relation import ApiRelation
from app.features.api_catalog.services.module_service import delete_modules, preview_module_delete
from app.features.test_management.models.test_case import TestCase as CaseModel
from app.lifecycle.service import batch_restore


@event.listens_for(Session, "do_orm_execute")
def _filter_soft_deleted(execute_state):
    if execute_state.is_select and not execute_state.execution_options.get("include_deleted", False):
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(SoftDeleteBase, lambda model: model.deleted_at.is_(None), include_aliases=True),
        )


def _database():
    engine = create_engine("sqlite://")
    tables = [
        User.__table__, Organization.__table__, Project.__table__, ProjectMember.__table__,
        OrganizationMember.__table__, ApiModule.__table__, ApiInterface.__table__, ApiRelation.__table__,
        CaseModel.__table__, RecycleBinItem.__table__, LifecycleAuditEvent.__table__,
    ]
    for table in tables:
        table.create(engine, checkfirst=True)
    return engine


def _module_fixture(db: Session):
    admin = User(username="api-admin", role="admin")
    db.add(admin)
    db.flush()
    project = Project(name="module recycle project", owner_id=admin.id)
    db.add(project)
    db.flush()
    root = ApiModule(project_id=project.id, name="root")
    db.add(root)
    db.flush()
    child = ApiModule(project_id=project.id, name="child", parent_id=root.id)
    db.add(child)
    db.flush()
    interface = ApiInterface(
        project_id=project.id, module_id=child.id, name="long endpoint name",
        method="GET", path="/items",
    )
    db.add(interface)
    db.flush()
    relation = ApiRelation(
        project_id=project.id, source_api_id=interface.id, target_api_id=interface.id,
        relation_type="FOLLOW_UP",
    )
    db.add(relation)
    db.commit()
    return admin, project, root, child, interface, relation


def test_module_subtree_delete_counts_hidden_descendants_and_restores_original_tree():
    engine = _database()
    with Session(engine) as db:
        admin, project, root, child, interface, relation = _module_fixture(db)
        preview = preview_module_delete(db, project.id, [root.id, child.id], actor=admin)
        assert preview.root_names == ["root"]
        assert (preview.module_count, preview.interface_count) == (2, 1)

        deleted = delete_modules(db, project.id, [root.id, child.id], actor=admin)
        items = db.query(RecycleBinItem).filter(
            RecycleBinItem.id.in_(deleted.recycle_bin_item_ids),
        ).all()
        assert len({item.deletion_batch_id for item in items}) == 1
        assert {item.resource_type for item in items} == {"api_module", "api_interface", "api_relation"}

        restored = batch_restore(db, deleted.recycle_bin_item_ids, admin)
        assert restored["failed"] == 0, restored
        assert db.get(ApiModule, root.id).deleted_at is None
        assert db.get(ApiModule, child.id).parent_id == root.id
        assert db.get(ApiInterface, interface.id).module_id == child.id
        assert db.get(ApiRelation, relation.id).deleted_at is None
    engine.dispose()


def test_module_subtree_delete_rolls_back_all_rows_when_one_interface_is_referenced():
    engine = _database()
    with Session(engine) as db:
        admin, project, root, child, interface, _relation = _module_fixture(db)
        db.add(CaseModel(project_id=project.id, name="uses api", api_id=interface.id))
        db.commit()

        from fastapi import HTTPException
        import pytest

        with pytest.raises(HTTPException) as error:
            delete_modules(db, project.id, [root.id], actor=admin)
        assert error.value.status_code == 409
        assert db.query(RecycleBinItem).count() == 0
        assert db.get(ApiModule, root.id).deleted_at is None
        assert db.get(ApiModule, child.id).deleted_at is None
        assert db.get(ApiInterface, interface.id).deleted_at is None
    engine.dispose()
