"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from app.features.test_management.schemas import (
    TestAssertionCreate,
    TestCaseCreate,
    TestCaseDataCreate,
    TestCaseFixtureReplace,
    TestCasePreconditionCreate,
    TestCaseUpdate,
    TestStepCreate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_management.router.dependencies import _CASE


router = APIRouter()


@router.get("/projects/{project_id}/test-cases", response_model=list, summary="测试用例列表")
def list_cases(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    test_point_id: int | None = Query(None, ge=1),
    target_type: str | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
):
    """列出`cases`。"""
    return _CASE.list_cases(
        db, project_id, user, test_point_id=test_point_id, target_type=target_type,
        status=status, keyword=keyword, page=page, page_size=page_size,
    ).items


@router.post("/projects/{project_id}/test-cases", status_code=status.HTTP_201_CREATED, summary="新建测试用例")
def create_case(
    project_id: int, body: TestCaseCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建用例。"""
    return _CASE.create_case(db, project_id, body, actor=user)


@router.get("/test-cases/{case_id}", summary="测试用例基本信息")
def get_case(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取用例。"""
    return _CASE.get_case(db, case_id, user)


@router.get("/test-cases/{case_id}/detail", summary="测试用例聚合详情（前置条件/数据/步骤/断言）")
def get_case_detail(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """获取用例详情。"""
    return _CASE.get_case_detail(db, case_id, user)


@router.patch("/test-cases/{case_id}", summary="编辑测试用例（乐观锁）")
def update_case(
    case_id: int, body: TestCaseUpdate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """更新用例。"""
    return _CASE.update_case(db, case_id, body, actor=user)


@router.delete("/test-cases/{case_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试用例")
def delete_case(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除用例。"""
    _CASE.delete_case(db, case_id, actor=user)
    return None


@router.get("/test-cases/{case_id}/preconditions", response_model=list, summary="前置条件列表")
def list_preconditions(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`preconditions`。"""
    return _CASE.list_preconditions(db, case_id, user)


@router.post("/test-cases/{case_id}/preconditions", status_code=status.HTTP_201_CREATED, summary="新增前置条件")
def create_precondition(
    case_id: int, body: TestCasePreconditionCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建前置条件。"""
    return _CASE.create_precondition(db, case_id, body, actor=user)


@router.get("/test-cases/{case_id}/data", response_model=list, summary="测试数据列表")
def list_data(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出数据。"""
    return _CASE.list_data(db, case_id, user)


@router.post("/test-cases/{case_id}/data", status_code=status.HTTP_201_CREATED, summary="新增测试数据")
def create_data(
    case_id: int, body: TestCaseDataCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建数据。"""
    return _CASE.create_data(db, case_id, body, actor=user)


@router.get("/test-cases/{case_id}/fixtures", response_model=list, summary="所需 Fixture 列表")
def list_case_fixtures(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出用例`fixtures`。"""
    return _CASE.list_fixtures(db, case_id, user)


@router.put("/test-cases/{case_id}/fixtures", summary="整体替换所需 Fixture")
def replace_case_fixtures(
    case_id: int, body: TestCaseFixtureReplace,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """替换用例关联的固定数据。"""
    return _CASE.replace_fixtures(db, case_id, body, actor=user)


@router.get("/test-cases/{case_id}/steps", response_model=list, summary="测试步骤列表")
def list_steps(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`steps`。"""
    return _CASE.list_steps(db, case_id, user)


@router.post("/test-cases/{case_id}/steps", status_code=status.HTTP_201_CREATED, summary="新增测试步骤")
def create_step(
    case_id: int, body: TestStepCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建`step`。"""
    return _CASE.create_step(db, case_id, body, actor=user)


@router.get("/test-cases/{case_id}/assertions", response_model=list, summary="断言列表")
def list_assertions(case_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """列出`assertions`。"""
    return _CASE.list_assertions(db, case_id, user)


@router.post("/test-cases/{case_id}/assertions", status_code=status.HTTP_201_CREATED, summary="新增断言")
def create_assertion(
    case_id: int, body: TestAssertionCreate,
    db: Session = Depends(get_db), user: User = Depends(get_current_user),
):
    """创建断言。"""
    return _CASE.create_assertion(db, case_id, body, actor=user)
