"""Security Testing 服务层共享的可见性 / 可写性校验。

复制 test_management / test_data / mock_management 的 _access 口径
（红线：feature 之间不互 import service，可见性校验各自维护一份）。
权限语义：
- 读：viewer+；不可见与不存在共用 404（隐藏存在性）。
- 预览 / 执行 / 确认生成 / 确认高风险：member+；不足 403。
- 自定义策略与规则、改环境开关、改 Finding 状态：editor+（含推导的 owner、平台管理员）。

所有实体都冗余存储 project_id，回溯无需联表；找不到实体一律 404。
系统模板（scope=SYSTEM）没有 project_id，对所有项目可见，但只有编辑权限能改。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.platform.projects.services.access_service import check_writable, get_project_or_404, require_writable_project

from app.core.models.identity import User
from app.core.models.project import Project
from app.core.http.errors import (
    CODE_SECURITY_RULE_NOT_FOUND,
    CODE_SECURITY_STRATEGY_NOT_FOUND,
    AppError,
    forbidden,
    not_found,
)
from app.core.security.roles import (
    PROJECT_ROLE_EDITOR,
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    has_project_role,
    is_platform_admin,
    project_role_for,
)

from app.features.security_testing.models import SecurityMutationRule, SecurityStrategy








def require_manage_project(db: Session, project_id: int, user: User) -> Project:
    """取项目并校验可管理（editor+）；策略 / 规则 / 环境开关 / Finding 状态用。"""
    project = get_project_or_404(db, project_id, user)
    # 平台管理员视同项目 admin，可直接管理。
    if is_platform_admin(user):
        return project
    role = project_role_for(db, project, user)
    if not has_project_role(role, PROJECT_ROLE_EDITOR):
        raise forbidden("需要项目管理员权限")
    return project


# ---------------------------------------------------------------- 实体 → 项目回溯


def resolve_strategy_project_id(db: Session, strategy_id: int) -> int | None:
    """回溯策略所属项目；系统模板返回 None（跨项目可见）。"""
    row = db.get(SecurityStrategy, strategy_id)
    if row is None:
        raise AppError(
            "安全策略不存在", status_code=404, code=CODE_SECURITY_STRATEGY_NOT_FOUND,
        )
    return row.project_id


def resolve_rule_project_id(db: Session, rule_id: int) -> int | None:
    """回溯规则所属项目（经策略）；系统规则返回 None。"""
    row = db.get(SecurityMutationRule, rule_id)
    if row is None:
        raise AppError(
            "变异规则不存在", status_code=404, code=CODE_SECURITY_RULE_NOT_FOUND,
        )
    strategy = db.get(SecurityStrategy, row.strategy_id)
    return None if strategy is None else strategy.project_id
