"""资源路由；认证、响应模型与原 method/path 保持不变。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.features.test_data.schemas import (
    DataExecutionDetailResponse,
    FixtureCreate,
    FixtureDetailResponse,
    FixtureGenerateRequest,
    FixtureListResponse,
    FixtureOutputsReplace,
    FixtureStepsReplace,
    FixtureTreeNodeResponse,
    FixtureUpdate,
)
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.features.test_data.router.dependencies import _EXECUTION
from app.features.test_data.router.dependencies import _FIXTURE
from app.features.test_data.router.dependencies import _RUNTIME


router = APIRouter()


@router.get("/projects/{project_id}/fixtures", response_model=FixtureListResponse)
def list_fixtures(
    project_id: int,
    keyword: str | None = Query(None),
    entity_type: str | None = Query(None),
    status: str | None = Query(None),
    scope: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureListResponse:
    """列出`fixtures`。"""
    return _FIXTURE.list_fixtures(
        db, project_id, user,
        keyword=keyword, entity_type=entity_type, status=status, scope=scope,
        page=page, page_size=page_size,
    )


@router.post("/projects/{project_id}/fixtures", response_model=FixtureDetailResponse, status_code=201)
def create_fixture(
    project_id: int,
    body: FixtureCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureDetailResponse:
    """创建固定数据。"""
    return _FIXTURE.create_fixture(db, project_id, body, actor=user)


@router.get("/fixtures/{fixture_id}", response_model=FixtureDetailResponse)
def get_fixture(
    fixture_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureDetailResponse:
    """获取固定数据。"""
    return _FIXTURE.get_fixture(db, fixture_id, user)


@router.patch("/fixtures/{fixture_id}", response_model=FixtureDetailResponse)
def update_fixture(
    fixture_id: int,
    body: FixtureUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureDetailResponse:
    """更新固定数据。"""
    return _FIXTURE.update_fixture(db, fixture_id, body, actor=user)


@router.delete("/fixtures/{fixture_id}", status_code=204)
def delete_fixture(
    fixture_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除固定数据。"""
    _FIXTURE.delete_fixture(db, fixture_id, actor=user)


@router.put("/fixtures/{fixture_id}/steps", response_model=FixtureDetailResponse)
def replace_fixture_steps(
    fixture_id: int,
    body: FixtureStepsReplace,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureDetailResponse:
    """替换固定数据的生成步骤。"""
    return _FIXTURE.replace_steps(db, fixture_id, body, actor=user)


@router.put("/fixtures/{fixture_id}/outputs", response_model=FixtureDetailResponse)
def replace_fixture_outputs(
    fixture_id: int,
    body: FixtureOutputsReplace,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FixtureDetailResponse:
    """替换固定数据的输出契约。"""
    return _FIXTURE.replace_outputs(db, fixture_id, body, actor=user)


@router.get("/fixtures/{fixture_id}/dependencies", response_model=list[FixtureTreeNodeResponse])
def fixture_dependency_tree(
    fixture_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FixtureTreeNodeResponse]:
    """构建固定数据及其依赖关系树。"""
    return _FIXTURE.dependency_tree(db, fixture_id, user)


@router.post("/fixtures/{fixture_id}/generate", response_model=DataExecutionDetailResponse)
def generate_fixture(
    fixture_id: int,
    body: FixtureGenerateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataExecutionDetailResponse:
    """手工试跑：返回执行记录详情（每步 input/output/error）。"""
    data_exec = _RUNTIME.generate(db, fixture_id, body, actor=user)
    return _EXECUTION.get_execution(db, data_exec.id, user)


@router.post("/fixtures/{fixture_id}/cleanup", response_model=DataExecutionDetailResponse)
def cleanup_fixture(
    fixture_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DataExecutionDetailResponse:
    """按最近一次试跑输出做 MANUAL cleanup。"""
    data_exec = _RUNTIME.cleanup(db, fixture_id, actor=user)
    return _EXECUTION.get_execution(db, data_exec.id, user)
