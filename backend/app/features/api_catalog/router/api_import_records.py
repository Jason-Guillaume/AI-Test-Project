"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.api_catalog.schemas import ApiImportRecordListResponse
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.api_catalog.router.dependencies import _API


router = APIRouter()


@router.get(
    "/projects/{project_id}/api-import-records",
    response_model=ApiImportRecordListResponse,
    summary="导入记录列表",
)
def list_import_records(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """列出`import`记录。"""
    items, total = _API.list_import_records(db, project_id, user, page=page, page_size=page_size)
    return ApiImportRecordListResponse(items=items, total=total)
