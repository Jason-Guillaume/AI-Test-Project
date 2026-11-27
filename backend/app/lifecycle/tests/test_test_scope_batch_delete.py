"""测试范围（test_scope）批量软删除与批量恢复顺序单元测试。

覆盖：
- 父子及多级嵌套目录同选时，服务端按稳定的子先父后顺序删除、父先子后恢复；
- 父节点仍有未勾选子目录或关联用例时被保留（409），已选空子目录仍可成功；
- 系统待整理节点、含用例目录与空目录混合提交返回准确的部分成功回执；
- 权限校验（只读成员被拒）与跨项目隔离（其他项目节点逐项失败且不泄露）。
"""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "Scope-Batch-Delete-Test-2026!safe-key")
os.environ.setdefault("DATABASE_URL", "sqlite://")

from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, with_loader_criteria

from app.core.database.soft_delete import SoftDeleteBase
from app.core.models.data_lifecycle import LifecycleAuditEvent, RecycleBinItem
from app.core.models.identity import Organization, OrganizationMember, User
from app.core.models.project import Project, ProjectMember
from app.features.test_management.models.test_case import TestCase as CaseModel
from app.features.test_management.models.test_scope import (
    TestCaseScope as CaseScopeModel,
    TestScopeNode as ScopeNodeModel,
)
from app.lifecycle.service import batch_delete, batch_restore


@event.listens_for(Session, "do_orm_execute")
def _filter_soft_deleted(execute_state):
    """在内存 SQLite 会话中启用与正式环境一致的软删除过滤。"""
    if execute_state.is_select and not execute_state.execution_options.get("include_deleted", False):
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(SoftDeleteBase, lambda model: model.deleted_at.is_(None), include_aliases=True),
        )


def _database():
    """构造仅包含测试范围生命周期所需表的隔离 SQLite 内存库。"""
    engine = create_engine("sqlite://")
    tables = [
        User.__table__,
        Organization.__table__,
        OrganizationMember.__table__,
        Project.__table__,
        ProjectMember.__table__,
        CaseModel.__table__,
        ScopeNodeModel.__table__,
        CaseScopeModel.__table__,
        RecycleBinItem.__table__,
        LifecycleAuditEvent.__table__,
    ]
    for table in tables:
        table.create(engine, checkfirst=True)
    return engine


def _seed_project(db: Session, name: str = "范围批删项目"):
    """创建管理员与项目。"""
    admin = User(username=f"admin-{name}", role="admin")
    db.add(admin)
    db.flush()
    project = Project(name=name, owner_id=admin.id)
    db.add(project)
    db.commit()
    return admin, project


def _scope(
    db: Session,
    project_id: int,
    name: str,
    *,
    direction: str = "API",
    parent_id: int | None = None,
    is_system: bool = False,
) -> ScopeNodeModel:
    """创建一个测试范围节点并提交。"""
    node = ScopeNodeModel(
        project_id=project_id,
        direction=direction,
        parent_id=parent_id,
        node_type="INBOX" if is_system else "FOLDER",
        name=name,
        sort_order=0,
        status="ACTIVE",
        is_system=is_system,
    )
    db.add(node)
    db.commit()
    return node


def _active_scope(db: Session, scope_id: int) -> ScopeNodeModel | None:
    """按默认软删除过滤查询活跃范围节点，绕过 identity map 缓存干扰。"""
    return db.query(ScopeNodeModel).filter(ScopeNodeModel.id == scope_id).first()


def test_parent_child_batch_delete_orders_children_first_and_batch_restore_orders_parents_first():
    """父子及三级嵌套乱序提交时，批删按子先父后全部成功，回收站批恢复按父先子后全部恢复。"""
    engine = _database()
    with Session(engine) as db:
        admin, project = _seed_project(db, "nested")
        grandparent = _scope(db, project.id, "一级目录")
        parent = _scope(db, project.id, "二级目录", parent_id=grandparent.id)
        child = _scope(db, project.id, "三级目录", parent_id=parent.id)

        # 故意按「祖父 → 父 → 子」顺序提交，验证服务端会稳定排序为子先父后。
        receipt = batch_delete(
            db, "test_scope", project.id, [grandparent.id, parent.id, child.id],
            actor=admin, reason="批量删除嵌套目录",
        )
        assert (receipt["succeeded"], receipt["failed"]) == (3, 0), receipt
        assert [item["id"] for item in receipt["items"]] == [child.id, parent.id, grandparent.id]
        assert _active_scope(db, child.id) is None
        assert _active_scope(db, parent.id) is None
        assert _active_scope(db, grandparent.id) is None

        # 故意按「子 → 父 → 祖父」顺序提交批量恢复，验证服务端按父先子后全部恢复。
        trash_ids = [item["recycle_bin_item_id"] for item in receipt["items"]]
        restored = batch_restore(db, trash_ids, admin)
        assert (restored["succeeded"], restored["failed"]) == (3, 0), restored
        assert _active_scope(db, grandparent.id) is not None
        assert _active_scope(db, parent.id).parent_id == grandparent.id
        assert _active_scope(db, child.id).parent_id == parent.id
    engine.dispose()


def test_parent_with_unselected_child_is_kept_while_selected_child_succeeds():
    """父节点下仍有未勾选的子目录时，已勾选子目录成功删除，父节点被依赖检查保留。"""
    engine = _database()
    with Session(engine) as db:
        admin, project = _seed_project(db, "partial-child")
        parent = _scope(db, project.id, "父目录", direction="UI")
        selected_child = _scope(db, project.id, "选中子目录", direction="UI", parent_id=parent.id)
        kept_child = _scope(db, project.id, "未选子目录", direction="UI", parent_id=parent.id)

        receipt = batch_delete(
            db, "test_scope", project.id, [parent.id, selected_child.id],
            actor=admin, reason="部分子节点删除",
        )
        assert (receipt["succeeded"], receipt["failed"]) == (1, 1), receipt
        by_id = {item["id"]: item for item in receipt["items"]}
        assert by_id[selected_child.id]["succeeded"] is True
        assert by_id[parent.id]["succeeded"] is False
        assert "子节点" in (by_id[parent.id]["error"] or "")
        assert _active_scope(db, selected_child.id) is None
        assert _active_scope(db, parent.id) is not None
        assert _active_scope(db, kept_child.id) is not None
    engine.dispose()


def test_mixed_empty_occupied_and_system_scopes_return_partial_receipt():
    """混合提交两个空目录、一个含用例目录和系统待整理节点：成功 2 个，失败 2 个。"""
    engine = _database()
    with Session(engine) as db:
        admin, project = _seed_project(db, "mixed")
        inbox = _scope(db, project.id, "待整理", direction="AI", is_system=True)
        empty_a = _scope(db, project.id, "空目录 A", direction="AI")
        empty_b = _scope(db, project.id, "空目录 B", direction="AI")
        occupied = _scope(db, project.id, "含用例目录", direction="AI")
        case = CaseModel(project_id=project.id, name="保留用例", target_type="AI")
        db.add(case)
        db.flush()
        db.add(CaseScopeModel(test_case_id=case.id, scope_node_id=occupied.id))
        db.commit()

        receipt = batch_delete(
            db, "test_scope", project.id, [empty_a.id, occupied.id, inbox.id, empty_b.id],
            actor=admin, reason="混合批量删除",
        )
        assert (receipt["succeeded"], receipt["failed"]) == (2, 2), receipt
        by_id = {item["id"]: item for item in receipt["items"]}
        assert by_id[empty_a.id]["succeeded"] is True
        assert by_id[empty_b.id]["succeeded"] is True
        assert by_id[occupied.id]["succeeded"] is False
        assert "测试用例" in (by_id[occupied.id]["error"] or "")
        assert by_id[inbox.id]["succeeded"] is False
        assert "待整理" in (by_id[inbox.id]["error"] or "")
        assert _active_scope(db, occupied.id) is not None
        assert db.query(CaseModel).filter(CaseModel.id == case.id).first() is not None
    engine.dispose()


def test_viewer_denied_and_cross_project_scope_isolated():
    """只读成员无权批删（403）；传入其他项目目录 ID 逐项失败且不改动原项目。"""
    engine = _database()
    with Session(engine) as db:
        admin, project_a = _seed_project(db, "iso-a")
        project_b = Project(name="iso-b", owner_id=admin.id)
        db.add(project_b)
        db.commit()
        viewer = User(username="scope-viewer", role="test")
        db.add(viewer)
        db.flush()
        db.add(ProjectMember(project_id=project_a.id, user_id=viewer.id, role="viewer", created_by=admin.id))
        db.commit()

        scope_a = _scope(db, project_a.id, "项目A目录")
        scope_b = _scope(db, project_b.id, "项目B目录")

        with pytest.raises(HTTPException) as exc_info:
            batch_delete(db, "test_scope", project_a.id, [scope_a.id], actor=viewer, reason=None)
        assert exc_info.value.status_code == 403

        receipt = batch_delete(
            db, "test_scope", project_a.id, [scope_a.id, scope_b.id], actor=admin, reason=None,
        )
        assert (receipt["succeeded"], receipt["failed"]) == (1, 1), receipt
        by_id = {item["id"]: item for item in receipt["items"]}
        assert by_id[scope_a.id]["succeeded"] is True
        assert by_id[scope_b.id]["succeeded"] is False
        assert _active_scope(db, scope_a.id) is None
        assert _active_scope(db, scope_b.id) is not None
    engine.dispose()
