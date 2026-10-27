"""项目路由。

路径前缀 /api/v1/projects。所有接口需要登录，资源级权限由服务层校验：
- viewer：只读
- member：可写项目内数据
- editor：可维护项目配置与资产
- owner / admin：项目负责人与平台管理员

响应约定：所有列表接口返回 {items, total, page, page_size} 信封。
越权访问统一按 404 处理（不返回 403），避免泄漏他人项目的存在性。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.environment_configuration.schemas import (
    EnvironmentListResponse,
    EnvironmentResponse,
    ProjectEnvironmentCreate,
    ProjectEnvironmentUpdate,
)
from app.features.environment_configuration.services.environment_service import (
    create_project_environment,
    deactivate_project_environment,
    list_project_environment_options,
    project_environment_response,
    set_project_default_environment,
    update_project_environment,
)
from app.features.projects.schemas import (
    OutboundTargetCreate,
    OutboundTargetResponse,
    OutboundTargetUpdate,
    PaginatedProjectResponse,
    ProjectCreate,
    ProjectDetailResponse,
    ProjectMemberCreate,
    ProjectMemberListResponse,
    ProjectMemberResponse,
    ProjectMemberUpdate,
    ProjectResponse,
    ProjectUpdate,
)
from app.features.projects.services.project_service import ProjectAdminService
from app.models.identity import Organization, User
from app.models.project import Project, ProjectMember, ProjectOutboundTarget
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.dependencies import get_db as _db_dep  # noqa: F401  (统一依赖入口)
from app.shared.errors import not_found
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.shared.roles import project_role_for

router = APIRouter(prefix="/projects", tags=["项目管理"])
# 服务实例无状态，路由层复用一个单例即可。
SERVICE = ProjectAdminService()


def _response(db: Session, project: Project, user: User) -> ProjectResponse:
    """构造单个项目响应，附带当前用户有效角色与成员数。

    Args:
        db: 数据库会话，用于联表查负责人与所属组织名。
        project: 已校验可见的项目实例。
        user: 当前登录用户，用于推导 my_role。

    Returns:
        项目响应体；负责人/组织已删除时对应名称回退为 None。
    """
    owner = db.get(User, project.owner_id)
    organization = db.get(Organization, project.organization_id) if project.organization_id else None
    return ProjectResponse(
        id=project.id,
        name=project.name,
        description=project.description,
        owner_id=project.owner_id,
        owner_username=owner.username if owner else None,
        organization_id=project.organization_id,
        organization_name=organization.name if organization else None,
        # 有效角色：成员身份或项目负责人/平台管理员，前端据此控制写按钮。
        my_role=project_role_for(db, project, user),
        # 成员数不含负责人，前端展示「负责人 + N 名成员」时不会重复计数。
        member_count=SERVICE.count_members(db, project.id),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _member_response(db: Session, row: ProjectMember, *, is_owner: bool = False) -> ProjectMemberResponse:
    """构造单个项目成员响应。

    Args:
        db: 数据库会话，用于联表查用户名。
        row: 成员表行。
        is_owner: 是否项目负责人，由调用方按 owner_id 比较后传入。

    Returns:
        成员响应体；用户已删除时 username 回退为 None。
    """
    member = db.get(User, row.user_id)
    return ProjectMemberResponse(
        user_id=row.user_id,
        username=member.username if member else None,
        role=row.role,
        is_owner=is_owner,
        created_by=row.created_by,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("", response_model=PaginatedProjectResponse)
def list_projects(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: str | None = None,
    organization_id: int | None = Query(None, ge=1),
):
    """分页列出当前用户可见的项目。

    分页参数由 FastAPI 约束：page 从 1 开始，page_size 不超过 MAX_PAGE_SIZE。
    可见性由 service 层过滤，平台管理员无过滤条件。
    """
    query = SERVICE.visible_projects_query(
        db, user, org_id=organization_id, keyword=keyword
    )
    # 先算总数再取当前页，避免 count 与分页查询结果不一致。
    total = int(query.count())
    items = (
        query.order_by(Project.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return PaginatedProjectResponse(
        items=[_response(db, item, user) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    body: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建项目；创建者自动成为负责人。"""
    project = SERVICE.create_project(db, body, actor=user)
    return _response(db, project, user)


@router.get("/{project_id}", response_model=ProjectDetailResponse)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """查询项目详情，附带成员列表。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    members = (
        db.query(ProjectMember)
        .filter(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.id)
        .all()
    )
    data = _response(db, project, user).model_dump()
    # 负责人也要出现在成员列表里，用 is_owner 标记区分，而不是额外插一行。
    data["members"] = [
        _member_response(db, row, is_owner=row.user_id == project.owner_id).model_dump()
        for row in members
    ]
    return ProjectDetailResponse(**data)


@router.get("/{project_id}/environments", response_model=EnvironmentListResponse)
def list_project_environments(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    include_inactive: bool = False,
):
    """列出当前用户可见项目中已绑定的环境；选择器响应不包含请求头密文。"""
    SERVICE.get_accessible_or_404(db, project_id, user)
    items = [
        EnvironmentResponse(**row)
        for row in list_project_environment_options(db, project_id, include_inactive=include_inactive)
    ]
    return EnvironmentListResponse(total=len(items), items=items, page=1, page_size=max(1, len(items)))


@router.post(
    "/{project_id}/environments",
    response_model=EnvironmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_project_environment_endpoint(
    project_id: int,
    body: ProjectEnvironmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建项目环境接口。"""
    SERVICE.get_accessible_or_404(db, project_id, user)
    row = create_project_environment(db, project_id, body, actor=user)
    return project_environment_response(db, row)


@router.patch("/{project_id}/environments/{environment_id}", response_model=EnvironmentResponse)
def update_project_environment_endpoint(
    project_id: int,
    environment_id: int,
    body: ProjectEnvironmentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新项目环境接口。"""
    SERVICE.get_accessible_or_404(db, project_id, user)
    row = update_project_environment(db, project_id, environment_id, body, actor=user)
    return project_environment_response(db, row)


@router.post(
    "/{project_id}/environments/{environment_id}/set-default",
    response_model=EnvironmentResponse,
)
def set_project_default_environment_endpoint(
    project_id: int,
    environment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """设置项目默认环境接口。"""
    SERVICE.get_accessible_or_404(db, project_id, user)
    row = set_project_default_environment(db, project_id, environment_id, actor=user)
    return project_environment_response(db, row)


@router.delete("/{project_id}/environments/{environment_id}", status_code=status.HTTP_204_NO_CONTENT)
def deactivate_project_environment_endpoint(
    project_id: int,
    environment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """停用项目环境绑定。"""
    SERVICE.get_accessible_or_404(db, project_id, user)
    deactivate_project_environment(db, project_id, environment_id, actor=user)
    return None


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    body: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """修改项目信息。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    project = SERVICE.update_project(db, project, body, actor=user)
    return _response(db, project, user)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除项目。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    SERVICE.delete_project(db, project, actor=user)
    return None


@router.post("/{project_id}/owner", response_model=ProjectResponse)
def transfer_owner(
    project_id: int,
    body: ProjectMemberCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把项目负责人转移给指定用户。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    project = SERVICE.transfer_owner(db, project, body.user_id, actor=user)
    return _response(db, project, user)


@router.get("/{project_id}/members", response_model=ProjectMemberListResponse)
def list_members(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
):
    """分页列出项目成员。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    items, total = SERVICE.page_members(db, project, page=page, page_size=page_size)
    return ProjectMemberListResponse(
        items=[
            _member_response(db, row, is_owner=row.user_id == project.owner_id)
            for row in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.put("/{project_id}/members/{member_id}", response_model=ProjectMemberResponse)
def upsert_member(
    project_id: int,
    member_id: int,
    body: ProjectMemberCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """新增或更新项目成员角色。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    # 路径上的 member_id 必须与请求体一致，否则无法确定要改哪一行。
    if member_id != body.user_id:
        raise not_found("成员 ID 不一致")
    row = SERVICE.upsert_member(db, project, body, actor=user)
    return _member_response(db, row, is_owner=row.user_id == project.owner_id)


@router.patch("/{project_id}/members/{member_id}", response_model=ProjectMemberResponse)
def update_member_role(
    project_id: int,
    member_id: int,
    body: ProjectMemberUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """修改项目成员角色。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    row = SERVICE.upsert_member(
        db, project, ProjectMemberCreate(user_id=member_id, role=body.role), actor=user
    )
    return _member_response(db, row, is_owner=row.user_id == project.owner_id)


@router.delete("/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    project_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """移除项目成员。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    SERVICE.remove_member(db, project, member_id, actor=user)
    return None


@router.get("/{project_id}/targets", response_model=list[OutboundTargetResponse])
def list_targets(
    project_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出项目出站目标。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    return SERVICE.list_outbound_targets(db, project)


@router.post(
    "/{project_id}/targets",
    response_model=OutboundTargetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_target(
    project_id: int,
    body: OutboundTargetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """新增项目出站目标。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    row = SERVICE.create_outbound_target(db, project, body, actor=user)
    return row


@router.patch("/{project_id}/targets/{target_id}", response_model=OutboundTargetResponse)
def update_target(
    project_id: int,
    target_id: int,
    body: OutboundTargetUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """更新出站目标开关。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    row = db.get(ProjectOutboundTarget, target_id)
    # 跨项目越权防护：目标必须确实属于路径上的项目，否则按不存在处理。
    if row is None or row.project_id != project.id:
        raise not_found("出站目标不存在")
    return SERVICE.update_outbound_target(db, project, row, enabled=body.enabled, actor=user)


@router.delete("/{project_id}/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_target(
    project_id: int,
    target_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除出站目标。"""
    project = SERVICE.get_accessible_or_404(db, project_id, user)
    row = db.get(ProjectOutboundTarget, target_id)
    if row is None or row.project_id != project.id:
        raise not_found("出站目标不存在")
    SERVICE.delete_outbound_target(db, project, row, actor=user)
    return None
