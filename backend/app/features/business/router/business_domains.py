"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.features.business.schemas import (
    BusinessDomainCreate,
    BusinessDomainListResponse,
    BusinessDomainResponse,
    BusinessDomainUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.business.router.dependencies import _DOMAIN


router = APIRouter()


@router.get(
    "/projects/{project_id}/business-domains",
    response_model=BusinessDomainListResponse,
    summary="业务域列表（keyword/status 过滤）",
)
def list_domains(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: str | None = Query(None),
    status: str | None = Query(None),
):
    """列出`domains`。"""
    return _DOMAIN.list_domains(
        db, project_id, user, keyword=keyword, status=status, page=page, page_size=page_size
    )


@router.post(
    "/projects/{project_id}/business-domains",
    response_model=BusinessDomainResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建业务域",
)
def create_domain(
    project_id: int,
    body: BusinessDomainCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建领域。"""
    return _DOMAIN.create_domain(db, project_id, body, actor=user)


@router.get("/business-domains/{domain_id}", response_model=BusinessDomainResponse, summary="业务域详情")
def get_domain(domain_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取领域。"""
    return _DOMAIN.get_domain(db, domain_id, user)


@router.patch("/business-domains/{domain_id}", response_model=BusinessDomainResponse, summary="编辑业务域")
def update_domain(
    domain_id: int,
    body: BusinessDomainUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新领域。"""
    return _DOMAIN.update_domain(db, domain_id, body, actor=user)


@router.delete(
    "/business-domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除业务域（级联清理下属流程/动作/绑定）",
)
def delete_domain(domain_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除领域。"""
    _DOMAIN.delete_domain(db, domain_id, actor=user)
    return None
