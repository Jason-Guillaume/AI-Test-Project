"""环境配置路由。

路径前缀 /api/v1/environments。该路由保留平台级环境类型目录的兼容管理接口；传入
project_id 时，管理员读取对应项目自己的目标地址与默认请求头。控制台选择器走
/projects/{project_id}/environments，只返回安全的项目环境选项，不包含请求头。

路径参数使用环境名（唯一标识）而非自增 ID。项目环境执行引用仍使用环境类型
ID，并由后端同时校验项目绑定。响应约定：列表接口返回 {items, total, page, page_size}。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.platform.environment_configuration.schemas import (
    EnvironmentCreate,
    EnvironmentListResponse,
    EnvironmentResponse,
    EnvironmentUpdate,
)
from app.platform.environment_configuration.services.environment_service import (
    create_environment,
    delete_environment,
    get_or_404,
    list_environments,
    list_project_environment_configs,
    response_for,
    set_default_environment,
    update_environment,
)
from app.core.security.auth import require_platform_admin
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.models.identity import User

router = APIRouter(prefix="/environments", tags=["环境配置"])


@router.get("", response_model=EnvironmentListResponse)
def list_environments_endpoint(
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    include_inactive: bool = False,
    project_id: int | None = Query(None, ge=1),
):
    """列出环境；默认只返回启用项，管理端可传 include_inactive=true 查看全部。

    默认环境置顶，其余按 ID 升序，与执行器的选择顺序一致。
    表为空时回退内置环境，避免前端出现空下拉框。
    """
    payloads = (
        list_project_environment_configs(db, project_id, include_inactive=include_inactive)
        if project_id is not None
        else list_environments(db, include_inactive=include_inactive)
    )
    items = [EnvironmentResponse(**payload) for payload in payloads]
    # 环境条目很少（个位数），先全量取出再切片分页，total 直接取列表长度。
    total = len(items)
    start = (page - 1) * page_size
    return EnvironmentListResponse(
        total=total,
        items=items[start : start + page_size],
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=EnvironmentResponse, status_code=status.HTTP_201_CREATED)
def create(body: EnvironmentCreate, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """新增环境；创建者自动获得写权限。"""
    row = create_environment(db, body, actor=actor)
    return response_for(row)


@router.get("/{name}", response_model=EnvironmentResponse)
def get_environment(name: str, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """按名称查询单个环境。"""
    return response_for(get_or_404(db, name))


@router.patch("/{name}", response_model=EnvironmentResponse)
def update(
    name: str,
    body: EnvironmentUpdate,
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
):
    """更新环境；环境名不可修改。"""
    row = update_environment(db, name, body, actor=actor)
    return response_for(row)


@router.post("/{name}/set-default", response_model=EnvironmentResponse)
def mark_default(name: str, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """把该环境设为默认环境。"""
    row = set_default_environment(db, name, actor=actor)
    return response_for(row)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete(name: str, db: Session = Depends(get_db), actor: User = Depends(require_platform_admin)):
    """删除环境；默认环境不可删除。"""
    delete_environment(db, name, actor=actor)
    return None
