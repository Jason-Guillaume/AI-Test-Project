"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.security.roles import PROJECT_ROLE_MEMBER, has_project_role, project_role_for


def assert_current_project_write(db: Session, project_id: int, actor: User) -> None:
    """每次后台业务副作用前复核用户仍有效且具备项目 member 权限。"""
    project = db.get(Project, project_id)
    if project is None or not actor.is_active:
        raise RuntimeError("任务项目或发起账号不可用")
    if not has_project_role(project_role_for(db, project, actor), PROJECT_ROLE_MEMBER):
        raise RuntimeError("任务发起者已失去项目成员权限，已停止新的业务操作")
