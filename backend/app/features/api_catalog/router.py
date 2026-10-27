"""接口管理路由。

单 APIRouter（无自身前缀），挂在 /api/v1 下，资源级路径与 plan 路由表一致：
- /projects/{project_id}/api-modules、/api-modules/{module_id}
- /projects/{project_id}/apis、/apis/{api_id}(/request|/responses|/relations|/history|/move|/debug)
- /api-relations/{relation_id}
- /projects/{project_id}/apis/import/(preview|confirm)、/projects/{project_id}/api-import-records

权限：
- 读：viewer+（service 内 _get_*_or_404 校验可见性，不可见→404）。
- 写：member+（service _check_writable）。
- 调试：require_platform_admin。
端点统一 sync def（httpx 同步 client 跑在 Starlette 线程池）。
service owns commit，router 不提交。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.api_catalog.schemas import (
    ApiChangeLogListResponse,
    ApiDebugRequest,
    ApiDebugResponse,
    ApiImportRecordListResponse,
    ApiInterfaceCreate,
    ApiInterfaceDetailResponse,
    ApiInterfaceListResponse,
    ApiInterfaceMove,
    ApiInterfaceUpdate,
    ApiModuleCreate,
    ApiModuleMove,
    ApiModuleResponse,
    ApiModuleUpdate,
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
from app.features.api_catalog.services.api_service import ApiService
from app.features.api_catalog.services.debug_service import DebugService
from app.features.api_catalog.services.import_service import ImportService
from app.models.identity import User
from app.shared.auth import get_current_user, require_platform_admin
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(tags=["接口管理"])

# 服务无状态，路由层复用单例。
_API = ApiService()
_IMPORT = ImportService()
_DEBUG = DebugService()


# ----------------------------------------------------------------------------- 模块


@router.get(
    "/projects/{project_id}/api-modules",
    response_model=list[ApiModuleResponse],
    summary="模块树（含未分类）",
)
def list_modules(project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`modules`。"""
    return _API.list_modules(db, project_id, user)


@router.post(
    "/projects/{project_id}/api-modules",
    response_model=ApiModuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建模块（≤2级）",
)
def create_module(
    project_id: int,
    body: ApiModuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建`module`。"""
    return _API.create_module(db, project_id, body, actor=user)


@router.patch("/api-modules/{module_id}", response_model=ApiModuleResponse, summary="编辑模块")
def update_module(
    module_id: int,
    body: ApiModuleUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新`module`。"""
    return _API.update_module(db, module_id, body, actor=user)


@router.patch("/api-modules/{module_id}/move", response_model=ApiModuleResponse, summary="移动模块")
def move_module(
    module_id: int,
    body: ApiModuleMove,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """移动模块。"""
    return _API.move_module(db, module_id, body, actor=user)


@router.delete(
    "/api-modules/{module_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除模块（未分类不可删；子接口归未分类）",
)
def delete_module(
    module_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除`module`。"""
    _API.delete_module(db, module_id, actor=user)
    return None


# ----------------------------------------------------------------------------- 接口


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


# ----------------------------------------------------------------------------- 请求参数/body


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


# ----------------------------------------------------------------------------- 响应


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


# ----------------------------------------------------------------------------- 关联


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


@router.delete(
    "/api-relations/{relation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除关联",
)
def delete_relation(
    relation_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除`relation`。"""
    _API.delete_relation(db, relation_id, actor=user)
    return None


# ----------------------------------------------------------------------------- 历史


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


# ----------------------------------------------------------------------------- 导入


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


# ----------------------------------------------------------------------------- 调试（仅平台管理员）


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
