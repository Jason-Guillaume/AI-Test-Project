"""项目访问服务。

集中承接跨业务域通用的项目可见与普通成员写入校验。领域资源到项目的回溯仍由
资源所属服务负责；项目设置、组织管理和高风险安全操作继续执行各自的额外授权。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.http.errors import forbidden, not_found
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.security.roles import (
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    has_project_role,
    project_role_for,
)


def get_project_or_404(db: Session, project_id: int, user: User) -> Project:
    """读取当前用户可见的项目；不可见与不存在统一返回 404。"""
    project = db.get(Project, project_id)
    if project is None:
        raise not_found("项目不存在")
    # 隐藏不可见项目的存在性，保持跨资源访问的统一 404 语义。
    if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_VIEWER):
        raise not_found("项目不存在")
    return project


def check_writable(db: Session, project: Project, actor: User) -> None:
    """校验普通项目写权限；可见但不足成员级别时返回 403。"""
    role = project_role_for(db, project, actor)
    if not has_project_role(role, PROJECT_ROLE_MEMBER):
        raise forbidden("需要项目成员权限")


def require_writable_project(db: Session, project_id: int, user: User) -> Project:
    """读取可见项目并要求普通成员级写权限。"""
    project = get_project_or_404(db, project_id, user)
    check_writable(db, project, user)
    return project
