"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.features.api_catalog.schemas import (
    ApiChangeLogListResponse,
    ApiDebugRequest,
    ApiDebugResponse,
    ApiInterfaceCreate,
    ApiInterfaceDetailResponse,
    ApiInterfaceListResponse,
    ApiInterfaceMove,
    ApiInterfaceUpdate,
    ApiRelationCreate,
    ApiRelationListResponse,
    ApiRelationResponse,
    ApiRequestBundle,
    ApiRequestBundleResponse,
    ApiResponsesBundle,
    ApiResponsesBundleResponse,
    ImportConfirmRequest,
    ImportConfirmResponse,
    ImportPreviewRequest,
    ImportPreviewResponse,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user, require_platform_admin
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.api_catalog.router.dependencies import _API
from app.features.api_catalog.router.dependencies import _DEBUG
from app.features.api_catalog.router.dependencies import _IMPORT


router = APIRouter()


@router.get(
    "/projects/{project_id}/apis",
    response_model=ApiInterfaceListResponse,
    summary="接口列表（keyword/method/module_id/status 过滤）",
)
def list_interfaces(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: str | None = Query(None),
    method: str | None = Query(None),
    module_id: int | None = Query(None, ge=1),
    status: str | None = Query(None),
):
    """列出`interfaces`。"""
    return _API.list_interfaces(
        db, project_id, user,
        keyword=keyword, method=method, module_id=module_id, status=status,
        page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/apis",
    response_model=ApiInterfaceDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="手工创建接口（source_type=MANUAL）",
)
def create_interface(
    project_id: int,
    body: ApiInterfaceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建接口。"""
    return _API.create_interface(db, project_id, body, actor=user)


@router.get("/apis/{api_id}", response_model=ApiInterfaceDetailResponse, summary="接口详情")
def get_interface(api_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取接口。"""
    return _API.get_interface(db, api_id, user)


@router.patch("/apis/{api_id}", response_model=ApiInterfaceDetailResponse, summary="编辑基本信息")
def update_interface(
    api_id: int,
    body: ApiInterfaceUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新接口。"""
    return _API.update_interface(db, api_id, body, actor=user)


@router.delete("/apis/{api_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除接口（级联子表）")
def delete_interface(api_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除接口。"""
    _API.delete_interface(db, api_id, actor=user)
    return None


@router.patch("/apis/{api_id}/move", response_model=ApiInterfaceDetailResponse, summary="移动接口到指定模块")
def move_interface(
    api_id: int,
    body: ApiInterfaceMove,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """移动接口。"""
    return _API.move_interface(db, api_id, body, actor=user)


@router.get("/apis/{api_id}/request", response_model=ApiRequestBundleResponse, summary="请求参数+body")
def get_request(api_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取请求。"""
    return _API.get_request(db, api_id, user)


@router.put("/apis/{api_id}/request", response_model=ApiRequestBundleResponse, summary="整体替换参数+body")
def save_request(
    api_id: int,
    body: ApiRequestBundle,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存请求。"""
    return _API.save_request(db, api_id, body, actor=user)


@router.get("/apis/{api_id}/responses", response_model=ApiResponsesBundleResponse, summary="响应列表")
def get_responses(api_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取`responses`。"""
    return _API.get_responses(db, api_id, user)


@router.put("/apis/{api_id}/responses", response_model=ApiResponsesBundleResponse, summary="整体替换响应")
def save_responses(
    api_id: int,
    body: ApiResponsesBundle,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """保存`responses`。"""
    return _API.save_responses(db, api_id, body, actor=user)


@router.get("/apis/{api_id}/relations", response_model=ApiRelationListResponse, summary="关联列表")
def list_relations(api_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`relations`。"""
    items = _API.list_relations(db, api_id, user)
    return ApiRelationListResponse(items=items, total=len(items))


@router.post(
    "/apis/{api_id}/relations",
    response_model=ApiRelationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新增关联",
)
def create_relation(
    api_id: int,
    body: ApiRelationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建`relation`。"""
    return _API.create_relation(db, api_id, body, actor=user)


@router.get("/apis/{api_id}/history", response_model=ApiChangeLogListResponse, summary="变更记录")
def list_history(
    api_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """列出`history`。"""
    items, total = _API.list_history(db, api_id, user, page=page, page_size=page_size)
    return ApiChangeLogListResponse(items=items, total=total)


@router.post(
    "/projects/{project_id}/apis/import/preview",
    response_model=ImportPreviewResponse,
    summary="导入预览（curl/openapi → 分类）",
)
def import_preview(
    project_id: int,
    body: ImportPreviewRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """预览接口定义导入结果。"""
    return _IMPORT.preview(db, project_id, body, actor=user)


@router.post(
    "/projects/{project_id}/apis/import/confirm",
    response_model=ImportConfirmResponse,
    status_code=status.HTTP_201_CREATED,
    summary="导入确认（幂等：重新解析+去重+入库）",
)
def import_confirm(
    project_id: int,
    body: ImportConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """确认并保存接口定义导入结果。"""
    return _IMPORT.confirm(db, project_id, body, actor=user)


@router.post(
    "/apis/{api_id}/debug",
    response_model=ApiDebugResponse,
    summary="调试发送真实请求（平台管理员 + 出站白名单）",
)
def debug_execute(
    api_id: int,
    body: ApiDebugRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_platform_admin),
):
    """执行接口调试请求并返回响应。"""
    return _DEBUG.execute(db, api_id, body, actor=user)
