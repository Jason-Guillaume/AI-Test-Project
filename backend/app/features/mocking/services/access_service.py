"""Mock Management 服务层共享的可见性 / 可写性校验。

复制 test_management / test_data 的 _access 口径（红线：feature 之间不互 import service.py，
可见性校验各自维护一份）。权限语义：
- 读：对该 project 至少 viewer；不可见与不存在共用 404（隐藏存在性）。
- 写：至少 member；不足 403（写操作语义上不存在「隐藏」，故用 403）。
- 管理 MockService / 重置 Token：项目 owner/admin（editor+）（§三十四）。

实体都冗余存储 project_id，回溯无需联表；找不到实体一律 404。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.mocking.models import (
    MockEndpoint,
    MockExecution,
    MockScenario,
    MockService,
)
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.http.errors import forbidden, not_found
from app.core.security.roles import (
    has_project_role,
    is_platform_admin,
    project_role_for,
)
from app.platform.projects.services.access_service import (
    check_writable,
    get_project_or_404,
    require_writable_project,
)

# MockService 管理 / Token 重置需要的更高权限：editor（项目管理员）以上。
_PROJECT_MANAGE_ROLE = "editor"


def require_manage_project(db: Session, project_id: int, user: User) -> Project:
    """取项目并校验可管理（editor+）；MockService 创建 / 删除 / 重置 Token 用。"""
    project = get_project_or_404(db, project_id, user)
    role = project_role_for(db, project, user)
    # 平台管理员视同项目 admin，可直接管理。
    if is_platform_admin(user):
        return project
    if not has_project_role(role, _PROJECT_MANAGE_ROLE):
        raise forbidden("需要项目管理员权限")
    return project


# ---------------------------------------------------------------- 实体 → 项目回溯


def resolve_service_project_id(db: Session, service_id: int) -> int:
    """解析并确定服务项目标识。"""
    row = db.get(MockService, service_id)
    if row is None:
        raise not_found("Mock 服务不存在")
    return row.project_id


def resolve_endpoint_project_id(db: Session, endpoint_id: int) -> int:
    """解析并确定接口项目标识。"""
    row = db.get(MockEndpoint, endpoint_id)
    if row is None:
        raise not_found("Mock 接口不存在")
    return row.project_id


def resolve_scenario_project_id(db: Session, scenario_id: int) -> int:
    """解析并确定场景项目标识。"""
    row = db.get(MockScenario, scenario_id)
    if row is None:
        raise not_found("Mock 场景不存在")
    return row.project_id


def resolve_execution_project_id(db: Session, execution_id: int) -> int:
    """解析并确定执行记录项目标识。"""
    row = db.get(MockExecution, execution_id)
    if row is None:
        raise not_found("Mock 调用记录不存在")
    return row.project_id
