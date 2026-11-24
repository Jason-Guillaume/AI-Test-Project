"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.test_management.schemas import (
    CaseExecutionListResponse,
    CaseExecutionResponse,
    TestRunListResponse,
    TestRunResponse,
)
from app.features.test_management.schemas.executions import RunCompareResponse
from app.features.test_management.services.compare_service import compare_runs
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_management.router.dependencies import _RUN


router = APIRouter()


@router.get("/test-runs/compare", response_model=RunCompareResponse, summary="比较同项目测试运行")
def compare_test_runs(
    baseline_run_id: int = Query(gt=0),
    candidate_run_id: int = Query(gt=0),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return compare_runs(db, baseline_run_id, candidate_run_id, user, page=page, page_size=page_size)


@router.get("/projects/{project_id}/test-runs/by-request/{request_key}", response_model=TestRunResponse)
def get_run_by_request(project_id: int, request_key: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    from app.features.test_management.models.execution import TestRun
    from app.platform.projects.services.access_service import get_project_or_404
    from app.core.http.errors import not_found
    get_project_or_404(db, project_id, user)
    run = db.query(TestRun).filter_by(project_id=project_id, request_key=request_key, created_by=user.id).first()
    if not run:
        raise not_found("测试执行记录不存在")
    return run


@router.get("/test-runs/{run_id}", response_model=TestRunResponse, summary="测试执行记录详情")
def get_run(run_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取运行。"""
    return _RUN.get_run(db, run_id, user)


@router.get("/test-runs/{run_id}/cases/{execution_id}", response_model=CaseExecutionResponse)
def get_case_execution(run_id: int, execution_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _RUN.get_case_execution(db, run_id, execution_id, user)


@router.get("/test-runs/{run_id}/cases", response_model=CaseExecutionListResponse, summary="用例执行记录列表")
def list_case_executions(run_id: int, page: int | None = Query(None, ge=1), page_size: int = Query(100, ge=1, le=100), failed_only: bool = False, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return _RUN.list_case_executions(db, run_id, user, page=page, page_size=page_size, failed_only=failed_only)


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
