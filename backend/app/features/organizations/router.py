"""组织模块路由。

路径前缀 /api/v1/organizations。所有接口需要登录；
成员/模型分配需要组织管理员，非平台管理员只能管理自己所属的组织。

响应约定：所有列表接口返回 {items, total, page, page_size} 信封，
与前端统一的 TanStack Query 列表处理保持一致。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.features.organizations.schemas import (
    CandidateResponse,
    MemberGrant,
    MemberListResponse,
    ModelOption,
    ModelOptionsResponse,
    OrganizationCreate,
    OrganizationMemberResponse,
    OrganizationResponse,
    OrganizationUpdate,
    PaginatedOrganizationResponse,
    UserCandidate,
)
from app.features.organizations.services.organization_service import (
    count_members,
    get_organization_or_404,
    remove_member,
    require_organization_admin,
    require_organization_member,
    upsert_member,
)
from app.models.configuration import ModelConfiguration
from app.models.identity import Organization, OrganizationMember, User
from app.shared.database import get_db
from app.shared.dependencies import get_current_user
from app.shared.errors import bad_request, not_found
from app.shared.roles import (
    ORG_ROLE_OWNER,
    is_platform_admin,
    organization_role,
)

router = APIRouter(prefix="/organizations", tags=["组织管理"])  # 组织前缀，与 users 的 /users、auth 的 /auth 平级


def _response(db: Session, organization: Organization, user: User) -> OrganizationResponse:
    """构造单个组织响应，附带当前用户在该组织内的有效角色与成员数。

    Args:
        db: 数据库会话，用于查询角色与成员数。
        organization: 目标组织。
        user: 当前登录用户，my_role 与 member_count 相对他计算。
    """
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        owner_id=organization.owner_id,
        my_role=organization_role(db, organization.id, user),  # 组织内有效角色（含 platform_admin 虚拟角色）
        created_at=organization.created_at,
        updated_at=organization.updated_at,
        member_count=count_members(db, organization.id),  # 附带成员数，避免前端再发一次请求
    )


def _member_response(row: OrganizationMember, *, is_org_owner: bool) -> OrganizationMemberResponse:
    """把成员表 ORM 行映射为响应体。

    成员行里的 role 是「组织内角色」，is_org_owner 由调用方根据
    organization.owner_id 计算，用于前端单独高亮负责人（负责人身份不再强制
    回写到 role 上，允许 owner 被降级为 admin/member）。

    Args:
        row: 组织成员表行。
        is_org_owner: 该成员是否为当前组织负责人。
    Returns:
        组织成员响应体。
    """
    return OrganizationMemberResponse(
        user_id=row.user_id,
        role=row.role,
        agent_enabled=row.agent_enabled,
        allowed_model_ids=list(row.allowed_model_ids or []),  # 允许为 None，统一以空列表返回
        is_org_owner=is_org_owner,
        created_at=row.created_at,
    )


@router.get("", response_model=PaginatedOrganizationResponse)
def list_organizations(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出当前用户可见的组织，并附带其在组织内的有效角色。

    Args:
        db: 数据库会话。
        user: 当前登录用户。
    Returns:
        统一信封的组织列表；组织总量不大，取全量后在信封里给出长度即可。
    """
    query = db.query(Organization)
    if not is_platform_admin(user):
        # 可见性边界：非平台管理员只能看到自己拥有的组织与自己作为成员加入的组织
        member_orgs = db.query(OrganizationMember.organization_id).filter(
            OrganizationMember.user_id == user.id
        )
        query = query.filter(
            (Organization.owner_id == user.id) | (Organization.id.in_(member_orgs))
        )
    organizations = query.order_by(Organization.id).all()  # 按 ID 稳定排序，避免分页跳动
    items = [_response(db, item, user) for item in organizations]
    return PaginatedOrganizationResponse(
        items=items,
        total=len(items),
        page=1,
        page_size=max(len(items), 1),  # 假分页：page_size 不能为 0，否则前端分页组件会报错
    )


@router.post("", response_model=OrganizationResponse, status_code=201)
def create_organization(
    body: OrganizationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建组织；创建者自动成为负责人，并写入 owner 成员行。

    Args:
        body: 组织名称入参。
        db: 数据库会话。
        user: 当前登录用户，同时作为新组织的负责人。
    Returns:
        新建组织的响应体。
    """
    name = body.name.strip()  # 去除首尾空白，避免「 测试组织  」与「测试组织」重复
    if len(name) < 2:
        raise bad_request("组织名称至少 2 个字符")  # 错误信封：名称过短
    existing = db.query(Organization).filter(Organization.name == name).first()
    if existing is not None:
        raise bad_request("组织名称已存在")  # 错误信封：名称冲突（全平台唯一）

    organization = Organization(name=name, owner_id=user.id)
    db.add(organization)
    db.flush()  # 先 flush 拿到自增 ID，成员行才能引用
    db.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role=ORG_ROLE_OWNER,  # 创建者自动是组织负责人（成员行角色）
            agent_enabled=False,  # 新建成员默认不开启 Agent 能力
            allowed_model_ids=[],  # 默认不分配模型，避免误用他人配置的模型
        )
    )
    db.commit()  # 事务提交点：组织与成员行必须同时成功
    db.refresh(organization)
    return _response(db, organization, user)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
def update_organization(
    organization_id: int,
    body: OrganizationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """修改组织名称；仅组织管理员可改。

    Args:
        organization_id: 目标组织 ID。
        body: 组织更新入参（仅名称）。
        db: 数据库会话。
        user: 当前登录用户。
    Returns:
        更新后的组织响应体。
    """
    require_organization_admin(db, organization_id, user)  # 权限判定：仅组织管理员/平台管理员
    organization = get_organization_or_404(db, organization_id)  # 不存在时抛 404
    name = (body.name or "").strip()  # 允许空字符串，但要统一 strip 后再判空
    if not name:
        raise bad_request("组织名称不能为空")  # 错误信封：空名称
    duplicate = (
        db.query(Organization)
        .filter(Organization.name == name, Organization.id != organization_id)  # 排除自身，允许「名称不变」
        .first()
    )
    if duplicate is not None:
        raise bad_request("组织名称已存在")  # 错误信封：与其他组织重名
    organization.name = name
    db.commit()  # 事务提交点
    db.refresh(organization)
    return _response(db, organization, user)


@router.get("/{organization_id}/members", response_model=MemberListResponse)
def list_members(
    organization_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出组织成员及其角色与模型授权。

    Args:
        organization_id: 目标组织 ID。
        db: 数据库会话。
        user: 当前登录用户，必须是该组织成员。
    Returns:
        组织成员列表响应信封。
    """
    require_organization_member(db, organization_id, user)  # 权限判定：必须为该组织成员（否则 404）
    organization = get_organization_or_404(db, organization_id)
    rows = (
        db.query(OrganizationMember)
        .filter(OrganizationMember.organization_id == organization_id)
        .order_by(OrganizationMember.id)  # 按成员行 ID 排序，负责人往往最靠前
        .all()
    )
    # is_org_owner 由 organization.owner_id 判定，不再依赖成员行 role，
    # 这样 owner 被降级后前端仍能正确标记负责人
    items = [_member_response(row, is_org_owner=row.user_id == organization.owner_id) for row in rows]
    return MemberListResponse(
        items=items,
        total=len(items),
        page=1,
        page_size=max(len(items), 1),  # 假分页：成员量小，统一信封
    )


@router.get("/{organization_id}/candidates", response_model=CandidateResponse)
def find_candidate(
    organization_id: int,
    username: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """按用户名搜索可加入组织的启用用户。

    负责人身份变更 / 新成员加入都会用到这个候选接口；只查启用账号，
    停用用户不会作为候选返回，避免出现「加入了但被禁用」的尴尬状态。

    Args:
        organization_id: 目标组织 ID，仅用于权限校验。
        username: 待搜索的用户名（精确匹配）。
        db: 数据库会话。
        user: 当前登录用户，必须是组织管理员。
    Returns:
        CandidateResponse；找不到匹配时 item 为 None。
    """
    require_organization_admin(db, organization_id, user)  # 权限判定：只有组织管理员可以拉取候选
    target = (
        db.query(User)
        .filter(User.username == username.strip(), User.is_active.is_(True))  # 只返回启用账号
        .first()
    )
    return CandidateResponse(
        item=UserCandidate(id=target.id, username=target.username, role=target.role, is_active=True)
        if target else None  # 未匹配到候选时 item 为 None，前端据此提示「未找到用户」
    )


@router.get("/{organization_id}/models", response_model=ModelOptionsResponse)
def available_models(
    organization_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """列出可分配给组织成员的启用模型。

    Args:
        organization_id: 目标组织 ID，仅用于权限校验（模型是平台级配置，不区分组织）。
        db: 数据库会话。
        user: 当前登录用户，必须是组织管理员。
    Returns:
        可分配模型选项列表。
    """
    require_organization_admin(db, organization_id, user)  # 权限判定：只有组织管理员可以查看/分配模型
    rows = (
        db.query(ModelConfiguration)
        .filter(ModelConfiguration.is_enabled.is_(True))  # 只返回平台启用的模型
        .order_by(ModelConfiguration.sort_order, ModelConfiguration.id)  # 按后台配置排序，其次按 ID 兜底
        .all()
    )
    items = [ModelOption(domain_id=row.domain_id, label=row.label) for row in rows]
    return ModelOptionsResponse(items=items, total=len(items))


@router.put("/{organization_id}/members/{member_id}", response_model=OrganizationMemberResponse)
def put_member(
    organization_id: int,
    member_id: int,
    body: MemberGrant,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """新增或更新组织成员、组织角色与模型授权。

    使用 PUT 语义保证幂等：不存在则新建成员行，存在则原地更新。
    模型授权只在校验通过（模型均存在且启用）后才落库。

    Args:
        organization_id: 目标组织 ID。
        member_id: 路径上的成员用户 ID，必须与请求体 user_id 一致。
        body: 成员授权入参（角色、Agent 开关、允许的模型列表）。
        db: 数据库会话。
        user: 当前登录用户，必须是组织管理员。
    Returns:
        更新后的成员响应体。
    """
    require_organization_admin(db, organization_id, user)  # 权限判定：只有组织管理员可以新增/调整成员
    if member_id != body.user_id:
        raise bad_request("路径成员 ID 与请求体不一致")  # 幂等保护：防止前端拼错参数导致误改他人

    organization = get_organization_or_404(db, organization_id)
    row = upsert_member(
        db,
        organization=organization,
        member_user_id=body.user_id,
        requested_role=body.role,
        agent_enabled=body.agent_enabled,
        allowed_model_ids=body.allowed_model_ids,  # 由 service 校验存在与启用状态后再落库
    )
    db.commit()  # 事务提交点
    db.refresh(row)
    return _member_response(row, is_org_owner=row.user_id == organization.owner_id)


@router.delete("/{organization_id}/members/{member_id}", status_code=204)
def delete_member(
    organization_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """移除组织成员（负责人不可移除；仍负责组织内项目的成员不可移除）。

    Args:
        organization_id: 目标组织 ID。
        member_id: 待移除成员的用户 ID。
        db: 数据库会话。
        user: 当前登录用户，必须是组织管理员。
    """
    require_organization_admin(db, organization_id, user)  # 权限判定：只有组织管理员可以移除成员
    organization = get_organization_or_404(db, organization_id)
    remove_member(db, organization=organization, member_user_id=member_id)  # 具体规则（负责人/项目归属）见 service
    db.commit()  # 事务提交点
    return None


@router.post("/{organization_id}/members/{member_id}/upgrade", response_model=OrganizationResponse)
def transfer_ownership(
    organization_id: int,
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """把组织负责人身份转移给另一名成员。

    原负责人在成员表中的角色不变，负责人身份由 organization.owner_id 记录；
    因此本接口不会因降级校验失败而无法转移。

    Args:
        organization_id: 目标组织 ID。
        member_id: 目标成员用户 ID，需为启用账号。
        db: 数据库会话。
        user: 当前登录用户，必须是组织管理员。
    Returns:
        更新后的组织响应体。
    """
    require_organization_admin(db, organization_id, user)  # 权限判定：只有组织管理员可以转移负责人
    organization = get_organization_or_404(db, organization_id)
    if organization.owner_id == member_id:
        # 幂等保护：目标已经是负责人时直接返回，不做任何变更
        return _response(db, organization, user)

    target = db.get(User, member_id)
    if target is None or not target.is_active:
        raise not_found("目标用户不存在或已停用")  # 错误信封：不允许把负责人交给停用/不存在账号

    row = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == member_id,
        )
        .first()
    )
    if row is None:
        # 目标还不是成员时先建一行；负责人也必须存在于成员表，便于后续统计与展示
        row = OrganizationMember(organization_id=organization_id, user_id=member_id)
        db.add(row)
    row.role = row.role or ORG_ROLE_OWNER  # 若角色为空则补齐为 owner，避免前端拿到空角色
    organization.owner_id = member_id  # 真正的负责人变更点：只改这个字段
    db.commit()  # 事务提交点
    db.refresh(organization)
    return _response(db, organization, user)
