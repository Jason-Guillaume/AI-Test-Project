"""缺陷路由。

路径前缀 /api/v1/bugs。所有接口需要登录，资源级权限由服务层校验：
- 读：viewer+（对该 project 有可见性）
- 写：member+（创建、修改、删除）
- 越权访问统一按 404 处理，避免泄露他人缺陷的存在性

响应约定：列表返回 {items, total, page, page_size} 信封。
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.defects.models.bug import Bug
from app.features.defects.schemas import (
    BugCreate,
    BugListResponse,
    BugResponse,
    BugUpdate,
    DefectSourceRequest,
    DefectSourceResponse,
)
from app.features.defects.services.defect_service import DefectService
from app.features.defects.services.source_service import DefectSourceService
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.security.auth import get_current_user
from app.core.database.session import get_db
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

router = APIRouter(prefix="/bugs", tags=["缺陷管理"])
# 服务实例无状态，路由层复用一个单例即可。
SERVICE = DefectService()
SOURCE_SERVICE = DefectSourceService()


def _response(db: Session, bug: Bug) -> BugResponse:
    """构造单个缺陷响应，联表补上项目名与用户名字段。

    负责人/组织/用户可能被删除，此时对应字段回退为 None 而非报错。
    """
    project = db.get(Project, bug.project_id)
    reporter = db.get(User, bug.reporter_id) if bug.reporter_id else None
    assignee = db.get(User, bug.assignee_id) if bug.assignee_id else None
    return BugResponse(
        id=bug.id,
        project_id=bug.project_id,
        project_name=project.name if project else None,
        title=bug.title,
        description=bug.description,
        severity=bug.severity,
        status=bug.status,
        steps_to_reproduce=bug.steps_to_reproduce,
        environment=bug.environment,
        reporter_id=bug.reporter_id,
        reporter_username=reporter.username if reporter else None,
        assignee_id=bug.assignee_id,
        assignee_username=assignee.username if assignee else None,
        created_at=bug.created_at,
        updated_at=bug.updated_at,
    )


@router.get("", response_model=BugListResponse)
def list_bugs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    project_id: int | None = Query(None, ge=1),
    status: str | None = Query(None),
    severity: int | None = Query(None, ge=1, le=4),
    assignee_id: int | None = Query(None, ge=1),
    keyword: str | None = None,
):
    """分页列出当前用户可见范围内的缺陷。

    可见性由 service 层过滤；platform admin 无过滤条件。
    """
    items, total = SERVICE.list_bugs(
        db,
        user=user,
        page=page,
        page_size=page_size,
        project_id=project_id,
        status=status,
        severity=severity,
        assignee_id=assignee_id,
        keyword=keyword,
    )
    return BugListResponse(
        items=[_response(db, item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/sources/context")
def source_context(source_type: Literal["CASE_EXECUTION", "SECURITY_FINDING"], source_id: int = Query(gt=0), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """读取授权来源的项目和测试运行编号，不返回敏感证据。"""
    return SOURCE_SERVICE.source_context(db, source_type, source_id, user)


@router.get("/sources", response_model=list[DefectSourceResponse])
def list_source_links(source_type: Literal["CASE_EXECUTION", "SECURITY_FINDING"], source_id: int = Query(gt=0), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """按真实来源查询授权范围内的缺陷关联。"""
    return SOURCE_SERVICE.list_for_source(db, source_type, source_id, user)


@router.post("/sources", response_model=DefectSourceResponse)
def link_source(body: DefectSourceRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """人工创建或关联缺陷，重复请求安全返回已有关系。"""
    return SOURCE_SERVICE.link(db, body, user)


@router.get("/{bug_id}/sources", response_model=list[DefectSourceResponse])
def list_bug_sources(bug_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """查询缺陷的真实来源。"""
    return SOURCE_SERVICE.list_for_bug(db, bug_id, user)


@router.get("/{bug_id}", response_model=BugResponse)
def get_bug(
    bug_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询缺陷详情；越权与不存在共用 404。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    return _response(db, bug)


@router.post("", response_model=BugResponse, status_code=status.HTTP_201_CREATED)
def create_bug(
    body: BugCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """新增缺陷；至少 member 权限。"""
    bug = SERVICE.create_bug(db, body, actor=user)
    return _response(db, bug)


@router.put("/{bug_id}", response_model=BugResponse)
def update_bug(
    bug_id: int,
    body: BugUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """修改缺陷；至少 member 权限。跟踪 status 与 assignee 变化并触发通知。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    bug = SERVICE.update_bug(db, bug, body, actor=user)
    return _response(db, bug)


@router.delete("/{bug_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bug(
    bug_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除缺陷；至少 member 权限。"""
    bug = SERVICE.get_bug_or_404(db, bug_id, user)
    SERVICE.delete_bug(db, bug, actor=user)
    return None
