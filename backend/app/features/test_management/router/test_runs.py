"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.test_management.schemas import (
    CaseExecutionListResponse,
    TestRunListResponse,
    TestRunResponse,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_management.router.dependencies import _RUN


router = APIRouter()


@router.get("/test-runs/{run_id}", response_model=TestRunResponse, summary="测试执行记录详情")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取运行。"""
    return _RUN.get_run(db, run_id, user)


@router.get("/test-runs/{run_id}/cases", response_model=CaseExecutionListResponse, summary="用例执行记录列表")
def list_case_executions(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出用例`executions`。"""
    return _RUN.list_case_executions(db, run_id, user)


@router.get("/projects/{project_id}/test-runs", response_model=TestRunListResponse, summary="项目测试执行记录列表")
def list_runs(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """列出`runs`。"""
    return _RUN.list_runs(db, project_id, user, page=page, page_size=page_size)
