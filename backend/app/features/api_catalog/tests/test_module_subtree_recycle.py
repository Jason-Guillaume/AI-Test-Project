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
from app.features.api_catalog.services.interface_service import list_interfaces
from app.features.api_catalog.services.module_service import delete_modules, preview_module_delete
from app.features.test_management.models.test_case import TestCase as CaseModel
from app.lifecycle.service import batch_delete, batch_restore


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


def test_empty_module_can_be_deleted_and_restored():
    engine = _database()
    with Session(engine) as db:
        admin, project, _root, _child, _interface, _relation = _module_fixture(db)
        empty = ApiModule(project_id=project.id, name="empty")
        db.add(empty)
        db.commit()

        preview = preview_module_delete(db, project.id, [empty.id], actor=admin)
        assert preview.root_names == ["empty"]
        assert (preview.module_count, preview.interface_count) == (1, 0)

        deleted = delete_modules(db, project.id, [empty.id], actor=admin)
        assert deleted.deleted_module_ids == [empty.id]
        assert deleted.deleted_interface_ids == []
        restored = batch_restore(db, deleted.recycle_bin_item_ids, admin)
        assert restored["failed"] == 0, restored
        assert db.get(ApiModule, empty.id).deleted_at is None
    engine.dispose()


def test_ungrouped_interface_batch_delete_only_removes_selected_rows():
    engine = _database()
    with Session(engine) as db:
        admin, project, _root, _child, _interface, _relation = _module_fixture(db)
        default_module = ApiModule(project_id=project.id, name="未分类", is_default=True)
        db.add(default_module)
        db.flush()
        selected = ApiInterface(
            project_id=project.id, module_id=None, name="selected ungrouped",
            method="POST", path="/ungrouped/selected",
        )
        untouched = ApiInterface(
            project_id=project.id, module_id=default_module.id, name="untouched ungrouped",
            method="GET", path="/ungrouped/untouched",
        )
        db.add_all([selected, untouched])
        db.commit()

        ungrouped = list_interfaces(db, project.id, admin, module_id=default_module.id)
        assert {row.id for row in ungrouped.items} == {selected.id, untouched.id}

        receipt = batch_delete(
            db, "api_interface", project.id, [selected.id],
            actor=admin, reason="删除选中的未分类接口",
        )
        assert receipt["succeeded"] == 1
        assert receipt["failed"] == 0
        assert db.get(ApiInterface, selected.id).deleted_at is not None
        assert db.get(ApiInterface, untouched.id).deleted_at is None
    engine.dispose()


def test_unclassified_module_batch_delete_clears_null_and_default_apis_and_restores():
    """勾选未分类删除时，清空 module_id=None 与 module_id=default 的全部接口且保留系统未分类行。"""
    engine = _database()
    with Session(engine) as db:
        admin, project, _root, _child, _interface, _relation = _module_fixture(db)
        default_module = ApiModule(project_id=project.id, name="未分类", is_default=True)
        db.add(default_module)
        db.flush()
        null_api = ApiInterface(
            project_id=project.id, module_id=None, name="null module api",
            method="GET", path="/unclassified/null",
        )
        default_api = ApiInterface(
            project_id=project.id, module_id=default_module.id, name="default module api",
            method="POST", path="/unclassified/default",
        )
        db.add_all([null_api, default_api])
        db.commit()

        preview = preview_module_delete(db, project.id, [default_module.id], actor=admin)
        assert preview.root_names == ["未分类"]
        assert (preview.module_count, preview.interface_count) == (0, 2)

        deleted = delete_modules(db, project.id, [default_module.id], actor=admin)
        assert deleted.deleted_module_ids == []
        assert set(deleted.deleted_interface_ids) == {null_api.id, default_api.id}
        assert db.get(ApiModule, default_module.id).deleted_at is None
        assert db.get(ApiInterface, null_api.id).deleted_at is not None
        assert db.get(ApiInterface, default_api.id).deleted_at is not None

        restored = batch_restore(db, deleted.recycle_bin_item_ids, admin)
        assert restored["failed"] == 0, restored
        assert db.get(ApiInterface, null_api.id).deleted_at is None
        assert db.get(ApiInterface, default_api.id).deleted_at is None
    engine.dispose()


def test_unclassified_delete_reports_referencing_test_cases_clearly():
    """未分类下存在被测试用例引用的接口时，拒绝删除并明确提示受影响接口和用例数。"""
    from fastapi import HTTPException
    import pytest

    engine = _database()
    with Session(engine) as db:
        admin, project, _root, _child, _interface, _relation = _module_fixture(db)
        default_module = ApiModule(project_id=project.id, name="未分类", is_default=True)
        db.add(default_module)
        db.flush()
        referenced_api = ApiInterface(
            project_id=project.id, module_id=None, name="登录接口",
            method="POST", path="/auth/login",
        )
        db.add(referenced_api)
        db.flush()
        db.add(CaseModel(project_id=project.id, name="登录用例", api_id=referenced_api.id))
        db.commit()

        with pytest.raises(HTTPException) as exc_info:
            delete_modules(db, project.id, [default_module.id], actor=admin)
        assert exc_info.value.status_code == 409
        assert "1 个接口正被 1 条测试用例引用" in str(exc_info.value.detail)
        assert "登录接口" in str(exc_info.value.detail)
        assert db.get(ApiInterface, referenced_api.id).deleted_at is None
    engine.dispose()
