"""环境配置路由。

路径前缀 /api/v1/environments。读写接口一律仅平台管理员可用：环境表里存的是
被测目标的 base_url 与默认请求头（可能含凭据），属于平台配置，第一阶段只对
平台管理侧开放。第二阶段若控制台需要环境选择器，应新增一个只返回名称与
显示名的只读接口，而不是放开本组接口。

路径参数使用环境名（唯一标识）而非自增 ID，与执行链路通过名称选择环境的
方式保持一致。响应约定：列表接口返回 {items, total, page, page_size}。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.environment_configuration.schemas import (
    EnvironmentCreate,
    EnvironmentListResponse,
    EnvironmentResponse,
    EnvironmentUpdate,
)
from app.features.environment_configuration.service import (
    create_environment,
    delete_environment,
    get_or_404,
    list_environments,
    response_for,
    set_default_environment,
    update_environment,
)
from app.shared.auth import require_platform_admin
from app.shared.database import get_db
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.models.identity import User

router = APIRouter(prefix="/environments", tags=["环境配置"])


@router.get("", response_model=EnvironmentListResponse)
def list_environments_endpoint(
    db: Session = Depends(get_db),
    actor: User = Depends(require_platform_admin),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    include_inactive: bool = False,
):
    """列出环境；默认只返回启用项，管理端可传 include_inactive=true 查看全部。

    默认环境置顶，其余按 ID 升序，与执行器的选择顺序一致。
    表为空时回退内置环境，避免前端出现空下拉框。
    """
    items = [
        EnvironmentResponse(**payload)
        for payload in list_environments(db, include_inactive=include_inactive)
    ]
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
