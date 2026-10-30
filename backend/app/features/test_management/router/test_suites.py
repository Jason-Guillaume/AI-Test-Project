"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.features.test_management.schemas import TestSuiteCaseAdd, TestSuiteCreate, TestSuiteUpdate
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_management.router.dependencies import _SUITE


router = APIRouter()


@router.get("/projects/{project_id}/test-suites", response_model=list, summary="测试套件列表")
def list_suites(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    suite_type: str | None = Query(None),
    keyword: str | None = Query(None),
):
    """列出`suites`。"""
    return _SUITE.list_suites(
        db, project_id, user, suite_type=suite_type, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.post("/projects/{project_id}/test-suites", status_code=status.HTTP_201_CREATED, summary="新建测试套件")
def create_suite(
    project_id: int, body: TestSuiteCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建套件。"""
    return _SUITE.create_suite(db, project_id, body, actor=user)


@router.get("/test-suites/{suite_id}", summary="测试套件详情")
def get_suite(suite_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取套件。"""
    return _SUITE.get_suite(db, suite_id, user)


@router.patch("/test-suites/{suite_id}", summary="编辑测试套件")
def update_suite(
    suite_id: int, body: TestSuiteUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新套件。"""
    return _SUITE.update_suite(db, suite_id, body, actor=user)


@router.delete("/test-suites/{suite_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试套件")
def delete_suite(suite_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除套件。"""
    _SUITE.delete_suite(db, suite_id, actor=user)
    return None


@router.get("/test-suites/{suite_id}/cases", response_model=list, summary="套件下的用例列表")
def list_suite_cases(suite_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出套件`cases`。"""
    return _SUITE.list_suite_cases(db, suite_id, user)


@router.post("/test-suites/{suite_id}/cases", status_code=status.HTTP_201_CREATED, summary="把用例加入套件")
def add_suite_case(
    suite_id: int, body: TestSuiteCaseAdd,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """添加套件用例。"""
    return _SUITE.add_suite_case(db, suite_id, body, actor=user)
