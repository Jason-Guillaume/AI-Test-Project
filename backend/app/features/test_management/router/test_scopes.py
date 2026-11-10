"""测试范围路由。读 viewer+，写 member+，事务在 ScopeService 内提交。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.features.test_management.schemas.scopes import (
    CaseAssetReplace,
    CaseAssetResponse,
    ScopeCaseArchiveRequest,
    ScopeCaseListResponse,
    ScopeCaseMoveRequest,
    ScopeLinkReplace,
    ScopeMutationResult,
    ScopeNodeCreate,
    ScopeNodeDetailResponse,
    ScopeNodeMove,
    ScopeNodeResponse,
    ScopeNodeUpdate,
    ScopePathResponse,
    ScopeStatsResponse,
    ScopeTreeResponse,
)
from app.features.test_management.services.scope_service import ScopeService

router = APIRouter()
_SCOPE = ScopeService()


@router.get("/projects/{project_id}/test-scopes", response_model=ScopeTreeResponse, summary="测试范围树")
def list_scopes(
    project_id: int,
    direction: str = Query(..., description="API、UI 或 AI"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出一个测试方向下的全部范围节点。"""
    return _SCOPE.list_tree(db, project_id, user, direction)


@router.get("/projects/{project_id}/test-scopes/stats", response_model=ScopeStatsResponse, summary="测试范围统计")
def scope_stats(
    project_id: int,
    direction: str = Query(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """汇总该方向的节点数、用例数、测试点数和优先级。"""
    return _SCOPE.stats(db, project_id, user, direction)


@router.post(
    "/projects/{project_id}/test-scopes",
    response_model=ScopeNodeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="新建测试范围节点",
)
def create_scope(
    project_id: int,
    body: ScopeNodeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建目录或资产链接节点。"""
    return _SCOPE.create_node(db, project_id, body, actor=user)


@router.get("/test-scopes/{node_id}", response_model=ScopeNodeDetailResponse, summary="测试范围节点详情")
def get_scope(node_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """读取节点、路径和下一层子节点。"""
    return _SCOPE.get_node(db, node_id, user)


@router.patch("/test-scopes/{node_id}", response_model=ScopeNodeResponse, summary="编辑测试范围节点")
def update_scope(
    node_id: int,
    body: ScopeNodeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """修改节点名称、说明、排序或状态。"""
    return _SCOPE.update_node(db, node_id, body, actor=user)


@router.post("/test-scopes/{node_id}/move", response_model=ScopeNodeResponse, summary="移动测试范围节点")
def move_scope(
    node_id: int,
    body: ScopeNodeMove,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """调整父节点和同级顺序。"""
    return _SCOPE.move_node(db, node_id, body, actor=user)


@router.delete("/test-scopes/{node_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除测试范围节点")
def delete_scope(node_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """删除没有子节点的目录，并把直接用例改挂到父级或待整理。"""
    _SCOPE.delete_node(db, node_id, actor=user)
    return None


@router.get(
    "/projects/{project_id}/test-scope-cases",
    response_model=ScopeCaseListResponse,
    summary="按测试范围查询用例",
)
def list_scope_cases(
    project_id: int,
    direction: str | None = Query(None),
    scope_node_id: int | None = Query(None, ge=1),
    include_descendants: bool = Query(True),
    case_type: str | None = Query(None),
    priority: str | None = Query(None),
    status: str | None = Query(None),
    keyword: str | None = Query(None),
    sort: str = Query("updated_at"),
    order: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按方向或节点分页查询用例。"""
    return _SCOPE.list_cases(
        db, project_id, user,
        direction=direction, scope_node_id=scope_node_id, include_descendants=include_descendants,
        case_type=case_type, priority=priority, status=status, keyword=keyword,
        sort=sort, order=order, page=page, page_size=page_size,
    )


@router.post(
    "/projects/{project_id}/test-scope-cases/move",
    response_model=ScopeMutationResult,
    summary="批量移动用例目录",
)
def move_scope_cases(
    project_id: int,
    body: ScopeCaseMoveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把用例移动到目标范围节点。"""
    return _SCOPE.move_cases(db, project_id, body, actor=user)


@router.post(
    "/projects/{project_id}/test-scope-cases/archive",
    response_model=ScopeMutationResult,
    summary="批量归档用例",
)
def archive_scope_cases(
    project_id: int,
    body: ScopeCaseArchiveRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把用例状态改为已废弃。"""
    return _SCOPE.archive_cases(db, project_id, body, actor=user)


@router.put("/test-cases/{case_id}/scope-links", response_model=list[ScopePathResponse], summary="替换用例目录归属")
def replace_scope_links(
    case_id: int,
    body: ScopeLinkReplace,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """整体替换一条用例挂靠的范围节点。"""
    return _SCOPE.replace_scope_links(db, case_id, body, actor=user)


@router.put("/test-cases/{case_id}/assets", response_model=list[CaseAssetResponse], summary="替换用例资产关联")
def replace_case_assets(
    case_id: int,
    body: CaseAssetReplace,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """整体替换用例关联的被测资产，不改执行外键。"""
    return _SCOPE.replace_assets(db, case_id, body, actor=user)
