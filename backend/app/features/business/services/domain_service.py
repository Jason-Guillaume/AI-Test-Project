"""业务域服务层。

路由层只做参数、认证与响应映射；业务、权限与事务集中在此。
权限口径与 defects / api_catalog 一致：读 viewer+、写 member+、越权与不存在共用 404。
service owns commit；router 不提交。
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.business.models.business_domain import BusinessDomain
from app.features.business.schemas import (
    BUSINESS_DOMAIN_STATUSES,
    BusinessDomainCreate,
    BusinessDomainListResponse,
    BusinessDomainResponse,
    BusinessDomainUpdate,
)
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.models.identity import User
from app.core.http.errors import bad_request, conflict, not_found
from app.core.notifications.notify import notify
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def _domain_response(domain: BusinessDomain) -> BusinessDomainResponse:
    """由 ORM 实例构造响应（ConfigDict(from_attributes=True) 已开启，直接 model_validate）。"""
    return BusinessDomainResponse.model_validate(domain)


def _ensure_unique_domain_name(
    db: Session, project_id: int, name: str, *, exclude_id: int | None = None
) -> None:
    """确保`unique`领域名称。"""
    query = db.query(BusinessDomain).filter(
        BusinessDomain.project_id == project_id, BusinessDomain.name == name
    )
    if exclude_id is not None:
        query = query.filter(BusinessDomain.id != exclude_id)
    if query.first() is not None:
        raise conflict("业务域名称已存在")


class DomainService:
    """业务域服务。无状态，路由层复用单例。"""

    def list_domains(
        self,
        db: Session,
        project_id: int,
        user: User,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> BusinessDomainListResponse:
        """按项目列出业务域（左侧目录树数据来源）。"""
        get_project_or_404(db, project_id, user)
        query = db.query(BusinessDomain).filter(BusinessDomain.project_id == project_id)
        kw = (keyword or "").strip()
        if kw:
            query = query.filter(
                or_(BusinessDomain.name.ilike(f"%{kw}%"), BusinessDomain.description.ilike(f"%{kw}%"))
            )
        if status:
            if status not in BUSINESS_DOMAIN_STATUSES:
                raise bad_request("业务域状态取值非法")
            query = query.filter(BusinessDomain.status == status)
        total = int(query.count())
        items = (
            query.order_by(BusinessDomain.sort.asc(), BusinessDomain.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return BusinessDomainListResponse(
            items=[_domain_response(d) for d in items], total=total, page=page, page_size=page_size
        )

    def create_domain(
        self, db: Session, project_id: int, body: BusinessDomainCreate, *, actor: User
    ) -> BusinessDomainResponse:
        """创建领域。"""
        project = require_writable_project(db, project_id, actor)
        name = body.name.strip()
        if not name:
            raise bad_request("业务域名称不能为空")
        _ensure_unique_domain_name(db, project_id, name)
        domain = BusinessDomain(
            project_id=project_id,
            name=name,
            description=(body.description or "").strip() or None,
            sort=body.sort,
            status=body.status,
        )
        db.add(domain)
        db.flush()
        notify(
            db,
            user_id=actor.id,
            event_type="business.domain.created",
            title=f"你已创建业务域「{domain.name}」",
            project_id=project_id,
            actor_id=actor.id,
            actor_username=actor.username,
            detail={"domain_id": domain.id, "project_id": project_id},
        )
        db.commit()
        db.refresh(domain)
        return _domain_response(domain)

    def get_domain(self, db: Session, domain_id: int, user: User) -> BusinessDomainResponse:
        """获取领域。"""
        domain = self._get_domain_or_404(db, domain_id, user)
        return _domain_response(domain)

    def update_domain(
        self, db: Session, domain_id: int, body: BusinessDomainUpdate, *, actor: User
    ) -> BusinessDomainResponse:
        """更新领域。"""
        domain = self._get_writable_domain_or_404(db, domain_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _domain_response(domain)
        if "name" in data and data["name"] is not None:
            new_name = data["name"].strip()
            if not new_name:
                raise bad_request("业务域名称不能为空")
            if new_name != domain.name:
                _ensure_unique_domain_name(db, domain.project_id, new_name, exclude_id=domain.id)
                domain.name = new_name
        for field in ("description", "sort", "status"):
            if field in data and data[field] is not None:
                setattr(domain, field, data[field])
        # description 允许清空：单独处理 None 直传。
        if "description" in data:
            domain.description = data["description"]
        db.flush()
        db.commit()
        db.refresh(domain)
        return _domain_response(domain)

    def delete_domain(self, db: Session, domain_id: int, *, actor: User) -> None:
        """删除领域。"""
        domain = self._get_writable_domain_or_404(db, domain_id, actor)
        # 级联删除由外键 ondelete=CASCADE 承担：删除域会一并清理其下流程→动作→绑定→映射。
        db.delete(domain)
        db.commit()

    # ---------------------------------------------------------------- 取实体

    def _get_domain_or_404(self, db: Session, domain_id: int, user: User) -> BusinessDomain:
        """获取领域或。"""
        domain = db.get(BusinessDomain, domain_id)
        if domain is None:
            raise not_found("业务域不存在")
        get_project_or_404(db, domain.project_id, user)
        return domain

    def _get_writable_domain_or_404(
        self, db: Session, domain_id: int, actor: User
    ) -> BusinessDomain:
        """获取可写领域或。"""
        domain = db.get(BusinessDomain, domain_id)
        if domain is None:
            raise not_found("业务域不存在")
        require_writable_project(db, domain.project_id, actor)
        return domain
