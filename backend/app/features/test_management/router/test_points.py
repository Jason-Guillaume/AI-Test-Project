"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.features.test_management.schemas import TestPointCreate, TestPointUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_management.router.dependencies import _POINT


router = APIRouter()


@router.get("/projects/{project_id}/test-points", response_model=list, summary="测试点列表")
def list_points(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    strategy_id: int | None = Query(None, ge=1),
    target_type: str | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
):
    """列出`points`。"""
    return _POINT.list_points(
        db, project_id, user, strategy_id=strategy_id, target_type=target_type,
        status=status, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.post("/projects/{project_id}/test-points", status_code=status.HTTP_201_CREATED, summary="新建测试点")
def create_point(
    project_id: int, body: TestPointCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建检查点。"""
    return _POINT.create_point(db, project_id, body, actor=user)


@router.get("/test-points/{point_id}", summary="测试点详情")
def get_point(point_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取检查点。"""
    return _POINT.get_point(db, point_id, user)


@router.patch("/test-points/{point_id}", summary="编辑测试点")
def update_point(
    point_id: int, body: TestPointUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新检查点。"""
    return _POINT.update_point(db, point_id, body, actor=user)


@router.delete("/test-points/{point_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试点")
def delete_point(point_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除检查点。"""
    _POINT.delete_point(db, point_id, actor=user)
    return None
