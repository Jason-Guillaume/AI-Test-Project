"""模型配置路由。

路径前缀 /api/v1/model-configs。全部接口仅平台管理员可用；
非管理员一律 403，不通过 404 隐藏平台级资源。

响应约定：列表接口返回 {items, total, page, page_size}。
响应体只含 has_api_key 与 masked_api_key，API Key 明文永不回传。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.model_configuration.schemas import (
    PROVIDER_LABELS,
    ModelConfigurationCreate,
    ModelConfigurationListResponse,
    ModelConfigurationResponse,
    ModelConfigurationUpdate,
    ProviderCatalogItem,
)
from app.features.model_configuration.services.model_config_service import (
    create_configuration,
    delete_configuration,
    get_or_404,
    response_for,
    set_default,
    update_configuration,
)
from app.shared.database import get_db
from app.shared.dependencies import require_platform_admin
from app.shared.errors import not_found
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.shared.roles import is_platform_admin
from app.models.configuration import ModelConfiguration
from app.models.identity import User
from app.shared.auth import get_current_user

router = APIRouter(prefix="/model-configs", tags=["模型配置"])


@router.get("/providers", response_model=list[ProviderCatalogItem])
def list_providers():
    """供应商目录，供前端下拉渲染。"""
    return [
        ProviderCatalogItem(value=key, label=value) for key, value in PROVIDER_LABELS.items()
    ]


@router.get("", response_model=ModelConfigurationListResponse)
def list_configurations(
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: str | None = None,
    is_enabled: bool | None = None,
):
    """分页列出模型配置，默认按排序值与 ID 升序。"""
    # 权限判定：这里故意用 403 而不是 404，模型配置属于平台级公开资源，不隐藏存在性。
    if not is_platform_admin(actor):
        from app.shared.errors import forbidden

        raise forbidden("仅管理员可执行该操作")
    query = db.query(ModelConfiguration)
    if is_enabled is not None:
        query = query.filter(ModelConfiguration.is_enabled.is_(is_enabled))
    if keyword:
        value = keyword.strip()
        pattern = f"%{value}%"
        query = query.filter(
            (ModelConfiguration.label.ilike(pattern))
            | (ModelConfiguration.model_name.ilike(pattern))
            | (ModelConfiguration.provider.ilike(pattern))
        )
    total = int(query.count())
    rows = (
        query.order_by(ModelConfiguration.sort_order.asc(), ModelConfiguration.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return ModelConfigurationListResponse(
        total=total,
        # 逐行走白名单映射，绝不直接返回 ORM 行，避免 api_key_encrypted 泄漏。
        items=[ModelConfigurationResponse(**response_for(row)) for row in rows],
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ModelConfigurationResponse, status_code=status.HTTP_201_CREATED)
def create(body: ModelConfigurationCreate, db: Session = Depends(get_db), actor: User = Depends(get_current_user)):
    """新增模型配置；API Key 只写入，不返回。"""
    row = create_configuration(db, body, actor=actor)
    return response_for(row)


@router.get("/{config_id}", response_model=ModelConfigurationResponse)
def get_config(
    config_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """查询单个模型配置。"""
    if not is_platform_admin(actor):
        from app.shared.errors import forbidden

        raise forbidden("仅管理员可执行该操作")
    return response_for(get_or_404(db, config_id))


@router.patch("/{config_id}", response_model=ModelConfigurationResponse)
def update(
    config_id: int,
    body: ModelConfigurationUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """更新模型配置；api_key 留空表示保留原密钥。"""
    row = update_configuration(db, config_id, body, actor=actor)
    return response_for(row)


@router.post("/{config_id}/set-default", response_model=ModelConfigurationResponse)
def mark_default(
    config_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """把该模型设为默认模型。"""
    row = set_default(db, config_id, actor=actor)
    return response_for(row)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    config_id: int,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """删除模型配置；默认模型不可删除。"""
    delete_configuration(db, config_id, actor=actor)
    return None
