"""ZAP 扫描模块的可见性 / 可写性校验。

复制 security_testing.services._access 的口径（红线：feature 之间不互 import service），
但本模块的实体是新表，所以实体→项目回溯要单独实现。

权限语义（§三十三）：
- Viewer：看历史 / 结果 / Finding / 报告（不可见与不存在共用 404）。
- Member：创建被动扫描、操作自己有权限的任务。
- Editor / Owner / Admin：管目标 / 认证配置 / 策略 / 批准受控主动扫描。
- 平台管理员：ZAP 服务连接配置与基础设施健康（走 admin 路由，不走这里）。

跨项目统一 404：本项目下找不到目标 / 策略 / 任务时一律 404，不返回 403，
避免用响应差异探测别的项目是否存在某个目标。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.platform.projects.services.access_service import get_project_or_404

from app.core.models.identity import User
from app.core.models.project import Project
from app.core.http.errors import (
    CODE_SECURITY_SCAN_AUTH_PROFILE_NOT_FOUND,
    CODE_SECURITY_SCAN_JOB_NOT_FOUND,
    CODE_SECURITY_SCAN_PROFILE_NOT_FOUND,
    CODE_SECURITY_SCAN_TARGET_NOT_FOUND,
    CODE_SECURITY_SCAN_TARGET_FORBIDDEN,
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




def require_member(db: Session, project: Project, actor: User) -> None:
    """写操作权限校验：至少 project member，不足 403。"""
    role = project_role_for(db, project, actor)
    if not has_project_role(role, PROJECT_ROLE_MEMBER):
        raise forbidden("需要项目成员权限")


def require_admin(db: Session, project: Project, actor: User) -> None:
    """管理操作权限校验：editor+（含平台管理员），不足 403。"""
    if is_platform_admin(actor):
        return
    role = project_role_for(db, project, actor)
    if not has_project_role(role, PROJECT_ROLE_EDITOR):
        raise forbidden("需要项目管理员权限")


def require_member_project(db: Session, project_id: int, user: User) -> Project:
    """取项目并校验可写（member+）；不可见 404，不可写 403。"""
    project = get_project_or_404(db, project_id, user)
    require_member(db, project, user)
    return project


def require_admin_project(db: Session, project_id: int, user: User) -> Project:
    """取项目并校验可管理（editor+）；不可见 404，不可管理 403。"""
    project = get_project_or_404(db, project_id, user)
    require_admin(db, project, user)
    return project


def target_forbidden() -> AppError:
    """扫描目标不存在或不属于当前项目（隐藏存在性）。"""
    return AppError(
        "扫描目标不存在", status_code=404, code=CODE_SECURITY_SCAN_TARGET_NOT_FOUND,
    )


def target_out_of_project() -> AppError:
    """目标属于别的项目：用 FORBIDDEN 码但仍是 404，避免泄露存在性。"""
    return AppError(
        "扫描目标不存在", status_code=404, code=CODE_SECURITY_SCAN_TARGET_FORBIDDEN,
    )


def profile_not_found() -> AppError:
    """扫描策略不存在或不属于当前项目（隐藏存在性）。"""
    return AppError(
        "扫描策略不存在", status_code=404, code=CODE_SECURITY_SCAN_PROFILE_NOT_FOUND,
    )


def auth_profile_not_found() -> AppError:
    """认证配置不存在或不属于当前项目（隐藏存在性）。"""
    return AppError(
        "认证配置不存在", status_code=404, code=CODE_SECURITY_SCAN_AUTH_PROFILE_NOT_FOUND,
    )


def job_not_found() -> AppError:
    """扫描任务不存在或不属于当前项目。"""
    return AppError(
        "扫描任务不存在", status_code=404, code=CODE_SECURITY_SCAN_JOB_NOT_FOUND,
    )
