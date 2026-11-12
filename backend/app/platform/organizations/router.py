"""组织模块 HTTP 适配器。

所有业务查询、授权规则和事务由 management_service 承接。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.platform.organizations.schemas import (
    CandidateResponse, MemberGrant, MemberListResponse, ModelOptionsResponse, OrganizationCreate,
    OrganizationMemberResponse, OrganizationResponse, OrganizationUpdate,
    PaginatedOrganizationResponse,
)
from app.platform.organizations.services import management_service as _management
from app.core.models.identity import User
from app.core.database.session import get_db
from app.core.http.dependencies import get_current_user

router = APIRouter(prefix="/organizations", tags=["组织管理"])

@router.get("", response_model=PaginatedOrganizationResponse)
def list_organizations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '列出当前用户可见的组织，并附带其在组织内的有效角色。\n\n    Args:\n        db: 数据库会话。\n        user: 当前登录用户。\n    Returns:\n        统一信封的组织列表；组织总量不大，取全量后在信封里给出长度即可。\n    '
    return _management.list_organizations(db=db, user=user)


@router.post("", response_model=OrganizationResponse, status_code=201)
def create_organization(
    body: OrganizationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '创建组织；创建者自动成为负责人，并写入 owner 成员行。\n\n    Args:\n        body: 组织名称入参。\n        db: 数据库会话。\n        user: 当前登录用户，同时作为新组织的负责人。\n    Returns:\n        新建组织的响应体。\n    '
    return _management.create_organization(body=body, db=db, user=user)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
def update_organization(
    organization_id: int,
    body: OrganizationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '修改组织名称；仅组织管理员可改。\n\n    Args:\n        organization_id: 目标组织 ID。\n        body: 组织更新入参（仅名称）。\n        db: 数据库会话。\n        user: 当前登录用户。\n    Returns:\n        更新后的组织响应体。\n    '
    return _management.update_organization(organization_id=organization_id, body=body, db=db, user=user)


@router.get("/{organization_id}/members", response_model=MemberListResponse)
def list_members(
    organization_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '列出组织成员及其角色与模型授权。\n\n    Args:\n        organization_id: 目标组织 ID。\n        db: 数据库会话。\n        user: 当前登录用户，必须是该组织成员。\n    Returns:\n        组织成员列表响应信封。\n    '
    return _management.list_members(organization_id=organization_id, db=db, user=user)


@router.get("/{organization_id}/candidates", response_model=CandidateResponse)
def find_candidate(
    organization_id: int,
    username: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '按用户名搜索可加入组织的启用用户。\n\n    负责人身份变更 / 新成员加入都会用到这个候选接口；只查启用账号，\n    停用用户不会作为候选返回，避免出现「加入了但被禁用」的尴尬状态。\n\n    Args:\n        organization_id: 目标组织 ID，仅用于权限校验。\n        username: 待搜索的用户名（精确匹配）。\n        db: 数据库会话。\n        user: 当前登录用户，必须是组织管理员。\n    Returns:\n        CandidateResponse；找不到匹配时 item 为 None。\n    '
    return _management.find_candidate(organization_id=organization_id, username=username, db=db, user=user)


@router.get("/{organization_id}/models", response_model=ModelOptionsResponse)
def available_models(
    organization_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '列出可分配给组织成员的启用模型。\n\n    Args:\n        organization_id: 目标组织 ID，仅用于权限校验（模型是平台级配置，不区分组织）。\n        db: 数据库会话。\n        user: 当前登录用户，必须是组织管理员。\n    Returns:\n        可分配模型选项列表。\n    '
    return _management.available_models(organization_id=organization_id, db=db, user=user)


@router.put("/{organization_id}/members/{member_id}", response_model=OrganizationMemberResponse)
def put_member(
    organization_id: int,
    member_id: int,
    body: MemberGrant,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '新增或更新组织成员、组织角色与模型授权。\n\n    使用 PUT 语义保证幂等：不存在则新建成员行，存在则原地更新。\n    模型授权只在校验通过（模型均存在且启用）后才落库。\n\n    Args:\n        organization_id: 目标组织 ID。\n        member_id: 路径上的成员用户 ID，必须与请求体 user_id 一致。\n        body: 成员授权入参（角色、Agent 开关、允许的模型列表）。\n        db: 数据库会话。\n        user: 当前登录用户，必须是组织管理员。\n    Returns:\n        更新后的成员响应体。\n    '
    return _management.put_member(organization_id=organization_id, member_id=member_id, body=body, db=db, user=user)


@router.delete("/{organization_id}/members/{member_id}", status_code=204)
def delete_member(
    organization_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '移除组织成员（负责人不可移除；仍负责组织内项目的成员不可移除）。\n\n    Args:\n        organization_id: 目标组织 ID。\n        member_id: 待移除成员的用户 ID。\n        db: 数据库会话。\n        user: 当前登录用户，必须是组织管理员。\n    '
    return _management.delete_member(organization_id=organization_id, member_id=member_id, db=db, user=user)


@router.post("/{organization_id}/members/{member_id}/upgrade", response_model=OrganizationResponse)
def transfer_ownership(
    organization_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    '把组织负责人身份转移给另一名成员。\n\n    原负责人在成员表中的角色不变，负责人身份由 organization.owner_id 记录；\n    因此本接口不会因降级校验失败而无法转移。\n\n    Args:\n        organization_id: 目标组织 ID。\n        member_id: 目标成员用户 ID，需为启用账号。\n        db: 数据库会话。\n        user: 当前登录用户，必须是组织管理员。\n    Returns:\n        更新后的组织响应体。\n    '
    return _management.transfer_ownership(organization_id=organization_id, member_id=member_id, db=db, user=user)


