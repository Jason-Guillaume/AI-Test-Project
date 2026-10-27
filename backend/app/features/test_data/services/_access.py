"""测试数据中心服务层共享的可见性 / 可写性校验。

复制 test_management.services._access 的口径（不复用其函数，避免 feature 之间
互相 import service，红线）。被测库连接与数据库策略需要平台管理员，见
`require_admin_project`。

权限口径：
- 读：对该 project 至少 viewer；不可见与不存在共用 404（隐藏存在性）。
- 写：至少 member；不足 403（写操作语义上不存在「隐藏」，故用 403）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.test_data.models.asset import TestDataAsset
from app.features.test_data.models.connection import (
    DatabaseAccessPolicy,
    TargetDatabaseConnection,
)
from app.features.test_data.models.execution import DataExecution
from app.features.test_data.models.fixture import Fixture
from app.features.test_data.models.pool import DataPool, DataPoolItem
from app.features.test_data.models.provider import DataProvider
from app.models.identity import User
from app.models.project import Project
from app.shared.errors import forbidden, not_found
from app.shared.roles import (
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    has_project_role,
    is_platform_admin,
    project_role_for,
)


def get_project_or_404(db: Session, project_id: int, user: User) -> Project:
    """取项目并校验可见性（viewer+）；不可见与不存在共用 404。"""
    project = db.get(Project, project_id)
    if project is None:
        raise not_found("项目不存在")
    if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_VIEWER):
        raise not_found("项目不存在")
    return project


def check_writable(db: Session, project: Project, actor: User) -> None:
    """写操作权限校验：至少 project member，不足 403。"""
    role = project_role_for(db, project, actor)
    if not has_project_role(role, PROJECT_ROLE_MEMBER):
        raise forbidden("需要项目成员权限")


def require_writable_project(db: Session, project_id: int, user: User) -> Project:
    """取项目并校验可写（member+）；不可见 404，不可写 403。"""
    project = get_project_or_404(db, project_id, user)
    check_writable(db, project, actor=user)
    return project


def require_admin(db: Session, user: User) -> User:
    """要求平台管理员；被测库连接与数据库策略的写权限只给平台管理员。"""
    if not is_platform_admin(user):
        raise forbidden("仅平台管理员可以管理被测库连接与数据库策略")
    return user


def require_admin_project(db: Session, project_id: int, user: User) -> Project:
    """取项目并要求平台管理员（连接/策略接口用）。"""
    project = get_project_or_404(db, project_id, user)
    require_admin(db, user)
    return project


# ---------------------------------------------------------------- 实体 → 项目回溯
# 本 feature 的实体都直接冗余存储 project_id，回溯无需联表。找不到实体一律 404，
# 避免上层把「实体不存在」误判成「无权」。


def resolve_fixture_project_id(db: Session, fixture_id: int) -> int:
    """解析并确定固定数据项目标识。"""
    row = db.get(Fixture, fixture_id)
    if row is None:
        raise not_found("Fixture 不存在")
    return row.project_id


def resolve_provider_project_id(db: Session, provider_id: int) -> int:
    """解析并确定提供器项目标识。"""
    row = db.get(DataProvider, provider_id)
    if row is None:
        raise not_found("数据 Provider 不存在")
    return row.project_id


def resolve_asset_project_id(db: Session, asset_id: int) -> int:
    """解析并确定资产项目标识。"""
    row = db.get(TestDataAsset, asset_id)
    if row is None:
        raise not_found("测试数据不存在")
    return row.project_id


def resolve_pool_project_id(db: Session, pool_id: int) -> int:
    """解析并确定连接池项目标识。"""
    row = db.get(DataPool, pool_id)
    if row is None:
        raise not_found("数据池不存在")
    return row.project_id


def resolve_pool_item_project_id(db: Session, item_id: int) -> int:
    """解析并确定连接池条目项目标识。"""
    item = db.get(DataPoolItem, item_id)
    if item is None:
        raise not_found("池条目不存在")
    pool = db.get(DataPool, item.pool_id)
    if pool is None:
        raise not_found("数据池不存在")
    return pool.project_id


def resolve_connection_project_id(db: Session, connection_id: int) -> int:
    """解析并确定连接项目标识。"""
    row = db.get(TargetDatabaseConnection, connection_id)
    if row is None:
        raise not_found("被测库连接不存在")
    return row.project_id


def resolve_execution_project_id(db: Session, data_execution_id: int) -> int:
    """解析并确定执行记录项目标识。"""
    row = db.get(DataExecution, data_execution_id)
    if row is None:
        raise not_found("造数执行记录不存在")
    return row.project_id


def resolve_policy_project_id(db: Session, policy_id: int) -> int:
    """解析并确定策略项目标识。"""
    row = db.get(DatabaseAccessPolicy, policy_id)
    if row is None:
        raise not_found("数据库访问策略不存在")
    return row.project_id
