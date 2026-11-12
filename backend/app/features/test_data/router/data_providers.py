"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.test_data.schemas import (
    DataExecutionDetailResponse,
    DataProviderCreate,
    DataProviderListResponse,
    DataProviderResponse,
    DataProviderTestRequest,
    DataProviderUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_data.router.dependencies import _EXECUTION
from app.features.test_data.router.dependencies import _PROVIDER
from app.features.test_data.router.dependencies import _RUNTIME


router = APIRouter()


@router.get(
    "/projects/{project_id}/data-providers", response_model=DataProviderListResponse,
)
def list_providers(
    project_id: int,
    provider_type: str | None = Query(None),
    enabled: bool | None = Query(None),
    keyword: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderListResponse:
    """列出`providers`。"""
    return _PROVIDER.list_providers(
        db, project_id, user,
        provider_type=provider_type, enabled=enabled, keyword=keyword,
        page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/data-providers",
    response_model=DataProviderResponse, status_code=201,
)
def create_provider(
    project_id: int,
    body: DataProviderCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderResponse:
    """创建提供器。"""
    return _PROVIDER.create_provider(db, project_id, body, actor=user)


@router.get("/data-providers/{provider_id}", response_model=DataProviderResponse)
def get_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderResponse:
    """获取提供器。"""
    return _PROVIDER.get_provider(db, provider_id, user)


@router.patch("/data-providers/{provider_id}", response_model=DataProviderResponse)
def update_provider(
    provider_id: int,
    body: DataProviderUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderResponse:
    """更新提供器。"""
    return _PROVIDER.update_provider(db, provider_id, body, actor=user)


@router.post("/data-providers/{provider_id}/enable", response_model=DataProviderResponse)
def enable_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderResponse:
    """启用数据提供器。"""
    return _PROVIDER.set_enabled(db, provider_id, enabled=True, actor=user)


@router.post("/data-providers/{provider_id}/disable", response_model=DataProviderResponse)
def disable_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataProviderResponse:
    """停用数据提供器。"""
    return _PROVIDER.set_enabled(db, provider_id, enabled=False, actor=user)


@router.delete("/data-providers/{provider_id}", status_code=204)
def delete_provider(
    provider_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除提供器。"""
    _PROVIDER.delete_provider(db, provider_id, actor=user)


@router.post("/data-providers/{provider_id}/test", response_model=DataExecutionDetailResponse)
def test_provider(
    provider_id: int,
    body: DataProviderTestRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataExecutionDetailResponse:
    """手工试跑单个 Provider，走完整安全策略。"""
    data_exec = _RUNTIME.test_provider(db, provider_id, body, actor=user)
    return _EXECUTION.get_execution(db, data_exec.id, user)
