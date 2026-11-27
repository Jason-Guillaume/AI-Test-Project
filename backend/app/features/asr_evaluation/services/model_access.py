"""文本模型授权与可选模型列表。

调优服务与调优 Worker 共用同一份校验，避免在旧对比服务退役后留下跨模块隐性依赖。
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.http.errors import not_found
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import OrganizationMember, User
from app.core.security.roles import is_platform_admin
from app.platform.projects.services.access_service import get_project_or_404


def require_model_access(db: Session, project_id: int, actor: User, model_config_id: int) -> None:
    """核对文本模型启用态与当前组织授权，避免借用其他项目凭据。"""
    project = get_project_or_404(db, project_id, actor)
    model = db.get(ModelConfiguration, model_config_id)
    if model is None or not model.is_enabled:
        raise not_found("文本模型配置不存在或已停用")
    if is_platform_admin(actor):
        return
    if project.organization_id is None:
        raise not_found("项目没有可用的组织模型授权")
    membership = db.query(OrganizationMember).filter(
        OrganizationMember.organization_id == project.organization_id,
        OrganizationMember.user_id == actor.id,
    ).first()
    allowed = {str(item) for item in (membership.allowed_model_ids or [])} if membership else set()
    if membership is None or not membership.agent_enabled or model.domain_id not in allowed:
        raise not_found("文本模型配置不存在")


def list_accessible_models(db: Session, project_id: int, actor: User) -> dict:
    """只返回项目和当前成员有权使用的启用文本模型摘要，不返回端点或凭据。"""
    get_project_or_404(db, project_id, actor)
    rows = db.query(ModelConfiguration).filter_by(is_enabled=True).order_by(
        ModelConfiguration.sort_order, ModelConfiguration.id,
    ).all()
    items = []
    for row in rows:
        try:
            require_model_access(db, project_id, actor, row.id)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            continue
        items.append({"id": row.id, "label": row.label, "model_name": row.model_name})
    return {"items": items, "total": len(items)}


__all__ = ["list_accessible_models", "require_model_access"]