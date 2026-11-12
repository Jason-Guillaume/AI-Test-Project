"""项目共享任务模板的权限、版本和输入快照服务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, or_, update
from sqlalchemy.orm import Session

from app.core.http.errors import conflict, not_found
from app.core.models.identity import User
from app.orchestration.tasks.models import TaskTemplate
from app.orchestration.tasks.schemas import TaskTemplateCreate, TaskTemplateStatusUpdate, TaskTemplateUpdate
from app.orchestration.tasks.services.access import TaskAccessService


def _config_snapshot(config) -> dict[str, Any]:
    """过滤临时浏览器会话、登录态引用和幂等键，仅保留可重新验证的配置。"""
    value = config.model_dump(exclude={"request_key", "template_id", "template_version"})
    value.pop("request_key", None)
    web_authoring = value.get("web_authoring")
    if isinstance(web_authoring, dict):
        web_authoring.pop("auth_profile_id", None)
    security = value.get("security_assessment")
    if isinstance(security, dict):
        security.pop("web_session_id", None)
    return value


def _response(row: TaskTemplate) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "name": row.name,
        "description": row.description,
        "config": row.config_json or {},
        "version": row.version,
        "is_active": row.is_active,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class TaskTemplateService:
    """模板列表、创建、版本化更新和停用。"""

    @staticmethod
    def list_templates(
        db: Session, project_id: int, actor: User, *, keyword: str = "", include_inactive: bool = False,
    ) -> list[dict[str, Any]]:
        TaskAccessService.get_project_for_read(db, project_id, actor)
        query = db.query(TaskTemplate).filter(TaskTemplate.project_id == project_id)
        if not include_inactive:
            query = query.filter(TaskTemplate.is_active.is_(True))
        term = keyword.strip()
        if term:
            pattern = f"%{term}%"
            query = query.filter(or_(TaskTemplate.name.ilike(pattern), TaskTemplate.description.ilike(pattern)))
        return [_response(row) for row in query.order_by(TaskTemplate.updated_at.desc(), TaskTemplate.id.desc()).all()]

    @staticmethod
    def get(db: Session, template_id: int, actor: User, *, write: bool = False) -> TaskTemplate:
        row = db.get(TaskTemplate, template_id)
        if row is None:
            raise not_found("任务模板不存在")
        (TaskAccessService.get_project_for_write if write else TaskAccessService.get_project_for_read)(
            db, row.project_id, actor,
        )
        return row

    @staticmethod
    def get_response(db: Session, template_id: int, actor: User) -> dict[str, Any]:
        return _response(TaskTemplateService.get(db, template_id, actor))

    @staticmethod
    def create(db: Session, project_id: int, body: TaskTemplateCreate, actor: User) -> dict[str, Any]:
        TaskAccessService.get_project_for_write(db, project_id, actor)
        row = TaskTemplate(
            project_id=project_id,
            created_by=actor.id,
            updated_by=actor.id,
            name=body.name.strip(),
            description=body.description.strip(),
            config_json=_config_snapshot(body.config),
            is_active=body.is_active,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _response(row)

    @staticmethod
    def update(db: Session, template_id: int, body: TaskTemplateUpdate, actor: User) -> dict[str, Any]:
        row = TaskTemplateService.get(db, template_id, actor, write=True)
        if row.version != body.expected_version:
            raise conflict("模板已被其他成员更新，请刷新并核对草稿后重试")
        result = db.execute(
            update(TaskTemplate)
            .where(TaskTemplate.id == template_id, TaskTemplate.version == body.expected_version)
            .values(
                name=body.name.strip(),
                description=body.description.strip(),
                config_json=_config_snapshot(body.config),
                is_active=row.is_active if body.is_active is None else body.is_active,
                version=TaskTemplate.version + 1,
                updated_by=actor.id,
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise conflict("模板已被其他成员更新，请刷新并核对草稿后重试")
        db.commit()
        db.expire(row)
        return _response(row)

    @staticmethod
    def set_active(
        db: Session, template_id: int, body: TaskTemplateStatusUpdate, actor: User,
    ) -> dict[str, Any]:
        row = TaskTemplateService.get(db, template_id, actor, write=True)
        if row.version != body.expected_version:
            raise conflict("模板状态已被其他成员更新，请刷新后重试")
        result = db.execute(
            update(TaskTemplate)
            .where(TaskTemplate.id == template_id, TaskTemplate.version == body.expected_version)
            .values(
                is_active=body.is_active,
                version=TaskTemplate.version + 1,
                updated_by=actor.id,
                updated_at=func.now(),
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise conflict("模板状态已被其他成员更新，请刷新后重试")
        db.commit()
        db.expire(row)
        return _response(row)

    @staticmethod
    def deactivate(db: Session, template_id: int, actor: User) -> None:
        row = TaskTemplateService.get(db, template_id, actor, write=True)
        row.is_active = False
        row.updated_by = actor.id
        row.updated_at = func.now()
        db.commit()
