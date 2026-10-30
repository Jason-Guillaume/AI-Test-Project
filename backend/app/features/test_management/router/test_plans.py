"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.features.test_management.schemas import (
    TestPlanCreate,
    TestPlanSuiteAdd,
    TestPlanUpdate,
    TestRunCreateRequest,
    TestRunResponse,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_management.router.dependencies import _PLAN
from app.features.test_management.router.dependencies import _RUN


router = APIRouter()


@router.get("/projects/{project_id}/test-plans", response_model=list, summary="测试计划列表")
def list_plans(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
):
    """列出`plans`。"""
    return _PLAN.list_plans(
        db, project_id, user, status=status, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.post("/projects/{project_id}/test-plans", status_code=status.HTTP_201_CREATED, summary="新建测试计划")
def create_plan(
    project_id: int, body: TestPlanCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建计划。"""
    return _PLAN.create_plan(db, project_id, body, actor=user)


@router.get("/test-plans/{plan_id}", summary="测试计划详情")
def get_plan(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取计划。"""
    return _PLAN.get_plan(db, plan_id, user)


@router.patch("/test-plans/{plan_id}", summary="编辑测试计划")
def update_plan(
    plan_id: int, body: TestPlanUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新计划。"""
    return _PLAN.update_plan(db, plan_id, body, actor=user)


@router.delete("/test-plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试计划")
def delete_plan(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除计划。"""
    _PLAN.delete_plan(db, plan_id, actor=user)
    return None


@router.get("/test-plans/{plan_id}/suites", response_model=list, summary="计划下的套件列表")
def list_plan_suites(plan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出计划`suites`。"""
    return _PLAN.list_plan_suites(db, plan_id, user)


@router.post("/test-plans/{plan_id}/suites", status_code=status.HTTP_201_CREATED, summary="把套件加入计划")
def add_plan_suite(
    plan_id: int, body: TestPlanSuiteAdd,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """添加计划套件。"""
    return _PLAN.add_plan_suite(db, plan_id, body, actor=user)


@router.post(
    "/test-plans/{plan_id}/runs",
    response_model=TestRunResponse,
    status_code=status.HTTP_200_OK,
    summary="触发测试计划执行（同步执行，返回完成的 TestRun）",
)
def create_run(
    plan_id: int, body: TestRunCreateRequest,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建运行。"""
    return _RUN.create_and_execute_run(db, plan_id, body, actor=user)
