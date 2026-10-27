"""认证与当前用户接口。

路径前缀 /api/v1/auth 与 /api/v1/users/me。
保留旧项目的自助注册规则：注册即创建个人组织并写入 owner 成员行，
因此任意注册用户都拥有至少一个组织，可直接进入控制台创建项目。

注册：
- POST /register 按 IP 限流，创建账号与个人组织后直接返回 TokenResponse（含 JWT）；
  前端写 localStorage 后直接进入对应控制台，无需二次登录

令牌语义（与旧项目一致）：
- 修改密码、禁用账号、调整平台角色都会递增 token_version，旧令牌立即失效
- 账号被禁用时令牌仍有效但返回 403「该账户已被禁用」，前端据此区分禁用与过期
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.features.organizations.schemas import OrganizationResponse, PaginatedOrganizationResponse
from app.features.organizations.services.organization_service import (
    count_members,
    ensure_personal_organization,
)
from app.features.users.schemas import (
    PasswordChange,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from app.features.users.services.user_service import UserAdminService, token_expires_in_seconds
from app.models.identity import Organization, OrganizationMember, User
from app.shared.auth import create_access_token, get_current_user
from app.shared.config import ACCESS_TOKEN_EXPIRE_MINUTES
from app.shared.database import get_db
from app.shared.errors import conflict
from app.shared.passwords import hash_password
from app.shared.rate_limit import enforce_auth_rate_limit
from app.shared.roles import is_platform_admin, organization_role

router = APIRouter(tags=["认证"])
SERVICE = UserAdminService()


def _org_response(db: Session, organization: Organization, user: User) -> OrganizationResponse:
    """把 ORM 组织对象映射为响应体：补上当前用户在该组织内的有效角色与成员数。

    Args:
        db: 数据库会话，用于查询角色与成员数。
        organization: 目标组织。
        user: 当前登录用户，my_role 相对他计算。
    """
    return OrganizationResponse(
        id=organization.id,
        name=organization.name,
        owner_id=organization.owner_id,
        my_role=organization_role(db, organization.id, user),
        created_at=organization.created_at,
        updated_at=organization.updated_at,
        member_count=count_members(db, organization.id),
    )


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register_user(body: UserCreate, request: Request, db: Session = Depends(get_db)):
    """自助注册：创建账号与个人组织，并直接签发访问令牌。

    Args:
        body: 用户名与密码。
        request: 用于取客户端地址做限流。
        db: 数据库会话。
    Returns:
        TokenResponse：含 access_token 与用户信息，前端写入后直接进入控制台。
    """
    enforce_auth_rate_limit(request, "register")  # 限流：按「注册」桶计数

    username = body.username.strip()
    SERVICE.validate_password(body.password)  # 业务层密码长度校验

    existing = db.query(User).filter(User.username == username).first()
    if existing is not None:
        # 旧项目在这里返回 404 隐藏用户名占用情况；新平台统一返回 409，
        # 让前端直接给出「用户名已存在」的表单提示（差异已在迁移文档标注）。
        raise conflict("用户名已存在")

    user = User(username=username, hashed_password=hash_password(body.password))
    db.add(user)
    db.flush()  # 先把用户落库拿到 ID，个人组织创建需要引用它
    ensure_personal_organization(db, user)  # 注册即拥有个人组织（含 owner 成员行）
    db.commit()  # 事务提交：用户与个人组织必须同时成功
    db.refresh(user)

    # 注册成功直接签发 token：登录态与注册态共用同一签发路径，避免前端二次往返。
    # create_access_token 只依赖 user.id 与 token_version，不校验密码，因此可在 flush 后调用。
    token = create_access_token(user)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=token_expires_in_seconds(ACCESS_TOKEN_EXPIRE_MINUTES),
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=TokenResponse)
def login_user(body: UserLogin, request: Request, db: Session = Depends(get_db)):
    """用户名密码登录，返回 JWT 与用户信息。

    Args:
        body: 用户名与密码。
        request: 用于取客户端地址做限流。
        db: 数据库会话。
    Returns:
        TokenResponse，含 access_token、有效期与用户信息。
    """
    enforce_auth_rate_limit(request, "login", username=body.username)  # 限流：按登录桶，并带上用户名细化统计
    user, token = SERVICE.authenticate(db, body)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=token_expires_in_seconds(ACCESS_TOKEN_EXPIRE_MINUTES),
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    """获取当前登录用户信息。

    Args:
        current_user: 由 get_current_user 依赖注入的当前用户。
    Returns:
        当前用户信息。
    """
    return current_user


@router.patch("/me", response_model=UserResponse)
def update_me(
    body: PasswordChange,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """修改自己的密码；成功后旧令牌立即失效，需要重新登录。

    Args:
        body: 旧密码与新密码。
        db: 数据库会话。
        current_user: 当前登录用户。
    Returns:
        更新后的用户信息。
    """
    SERVICE.change_password(
        db, current_user.id, body.old_password, body.new_password, actor=current_user
    )  # 服务层会递增 token_version，使当前令牌立即失效
    return current_user


@router.get("/me/organizations", response_model=PaginatedOrganizationResponse)
def my_organizations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """当前用户可见的组织列表，附带其在组织内的有效角色。

    Args:
        db: 数据库会话。
        current_user: 当前登录用户。
    Returns:
        统一信封的「我的组织」列表。
    """
    query = db.query(Organization)
    if not is_platform_admin(current_user):
        # 可见性边界：非平台管理员只能看到自己拥有的组织与自己作为成员加入的组织
        member_orgs = db.query(OrganizationMember.organization_id).filter(
            OrganizationMember.user_id == current_user.id
        )
        query = query.filter(
            (Organization.owner_id == current_user.id) | (Organization.id.in_(member_orgs))
        )
    organizations = query.order_by(Organization.id).all()
    # 个人与成员的组织数量很小，这里一次性取回全部而不是真分页
    items = [_org_response(db, org, current_user) for org in organizations]
    return PaginatedOrganizationResponse(
        items=items,
        total=len(items),
        page=1,
        page_size=max(len(items), 1),  # 保证 page_size 不为 0，满足前端分页组件的约束
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(current_user: User = Depends(get_current_user)):
    """退出登录：服务端不维护令牌会话，客户端删除本地令牌即可。

    Args:
        current_user: 当前登录用户，仅用于维持鉴权一致性。
    """
    return None
