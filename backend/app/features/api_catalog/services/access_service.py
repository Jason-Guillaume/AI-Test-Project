"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.core.models.project import Project
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_module import ApiModule
from app.core.models.identity import User
from app.core.http.errors import not_found
from app.core.security.roles import (
    PROJECT_ROLE_VIEWER,
    accessible_project_ids,
    has_project_role,
    project_role_for,
)
from app.platform.projects.services.access_service import check_writable, get_project_or_404


def get_interface_or_404(db: Session, api_id: int, user: User) -> ApiInterface:
    """读取当前用户可见的接口。"""
    iface = db.get(ApiInterface, api_id)
    if iface is None:
        raise not_found("接口不存在")
    visible_ids = accessible_project_ids(db, user)
    if visible_ids is not None and iface.project_id not in visible_ids:
        raise not_found("接口不存在")
    return iface


def get_writable_interface_or_404(db: Session, api_id: int, user: User) -> ApiInterface:
    """读取接口并要求其所属项目可写。"""
    iface = get_interface_or_404(db, api_id, user)
    project = db.get(Project, iface.project_id)
    if project is None:
        raise not_found("项目不存在")
    check_writable(db, project, user)
    return iface


def get_module_or_404(db: Session, module_id: int, user: User) -> ApiModule:
    """读取当前用户可见的 API 模块。"""
    mod = db.get(ApiModule, module_id)
    if mod is None:
        raise not_found("模块不存在")
    project = db.get(Project, mod.project_id)
    if project is None or not has_project_role(
        project_role_for(db, project, user), PROJECT_ROLE_VIEWER
    ):
        raise not_found("模块不存在")
    return mod


def get_writable_module_or_404(db: Session, module_id: int, user: User) -> ApiModule:
    """读取 API 模块并要求其所属项目可写。"""
    mod = get_module_or_404(db, module_id, user)
    project = db.get(Project, mod.project_id)
    if project is None:
        raise not_found("项目不存在")
    check_writable(db, project, user)
    return mod
