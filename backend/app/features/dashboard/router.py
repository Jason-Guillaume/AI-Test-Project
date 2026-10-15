"""看板路由。

路径前缀 /api/v1/dashboard。所有接口都需要登录，统计口径随当前用户授权范围变化：
- /overview        个人工作台总览（含 scope 说明）
- /projects        当前用户可见项目概况
- /ready           依赖就绪状态
- /platform        平台管理端统计，仅平台管理员可用
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.features.dashboard.schemas import (
    DashboardOverviewResponse,
    ProjectSummaryResponse,
    ReadyResponse,
)
from app.features.dashboard.services.dashboard_service import (
    overview_for_user,
    platform_statistics,
    project_summaries,
    readiness,
)
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.errors import forbidden
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.shared.roles import is_platform_admin

router = APIRouter(prefix="/dashboard", tags=["看板"])


@router.get("/overview", response_model=DashboardOverviewResponse)
def overview(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """个人工作台总览，统计范围见 scope 字段。"""
    return overview_for_user(db, current_user)


@router.get("/projects", response_model=ProjectSummaryResponse)
def projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """当前用户可见的项目概况列表。"""
    return project_summaries(db, current_user, page=page, page_size=page_size)


@router.get("/ready", response_model=ReadyResponse)
def ready(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """依赖就绪检查：数据库不可用返回 not_ready，其它依赖缺失为 degraded。"""
    return readiness(db)


@router.get("/platform", response_model=DashboardOverviewResponse)
def platform(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """平台级统计，仅平台管理员可用。"""
    if not is_platform_admin(current_user):
        raise forbidden("仅管理员可查看平台统计")
    return platform_statistics(db)
