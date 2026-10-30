"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_relation import ApiRelation
from app.features.api_catalog.schemas import ApiRelationCreate, ApiRelationResponse
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.http.errors import bad_request, conflict, not_found
from app.core.security.roles import PROJECT_ROLE_MEMBER, has_project_role, project_role_for
from app.features.api_catalog.services.access_service import get_interface_or_404
from app.features.api_catalog.services.access_service import get_writable_interface_or_404
from app.features.api_catalog.services.queries import interface_name_map
from app.features.api_catalog.services.response_mapper import relation_response


def list_relations(db: Session, api_id: int, user: User) -> list[ApiRelationResponse]:
    """列出`relations`。"""
    iface = get_interface_or_404(db, api_id, user)
    rels = (
        db.query(ApiRelation)
        .filter(
            (ApiRelation.source_api_id == iface.id) | (ApiRelation.target_api_id == iface.id)
        )
        .order_by(ApiRelation.id.asc())
        .all()
    )
    names = interface_name_map(db, [r.source_api_id for r in rels] + [r.target_api_id for r in rels])
    return [relation_response(r, names) for r in rels]


def create_relation(db: Session, api_id: int, body: ApiRelationCreate, *, actor: User
) -> ApiRelationResponse:
    """创建`relation`。"""
    iface = get_writable_interface_or_404(db, api_id, actor)
    if body.source_api_id != iface.id and body.target_api_id != iface.id:
        raise bad_request("关联必须涉及当前接口")
    source = db.get(ApiInterface, body.source_api_id)
    target = db.get(ApiInterface, body.target_api_id)
    if source is None or target is None:
        raise not_found("关联接口不存在")
    if source.project_id != iface.project_id or target.project_id != iface.project_id:
        raise bad_request("关联接口必须属于同一项目")
    if body.source_api_id == body.target_api_id:
        raise bad_request("不能关联接口自身")
    existing = (
        db.query(ApiRelation)
        .filter(
            ApiRelation.source_api_id == body.source_api_id,
            ApiRelation.target_api_id == body.target_api_id,
            ApiRelation.relation_type == body.relation_type,
            ApiRelation.variable_name == body.variable_name,
        )
        .first()
    )
    if existing is not None:
        raise conflict("该关联已存在")
    rel = ApiRelation(
        project_id=iface.project_id,
        source_api_id=body.source_api_id,
        target_api_id=body.target_api_id,
        relation_type=body.relation_type,
        variable_name=body.variable_name,
        extract_path=body.extract_path,
    )
    db.add(rel)
    db.flush()
    db.commit()
    db.refresh(rel)
    names = interface_name_map(db, [rel.source_api_id, rel.target_api_id])
    return relation_response(rel, names)


def delete_relation(db: Session, relation_id: int, *, actor: User) -> None:
    """删除`relation`。"""
    rel = db.get(ApiRelation, relation_id)
    if rel is None:
        raise not_found("关联不存在")
    project = db.get(Project, rel.project_id)
    if project is None or not has_project_role(
        project_role_for(db, project, actor), PROJECT_ROLE_MEMBER
    ):
        raise not_found("关联不存在")
    db.delete(rel)
    db.commit()
