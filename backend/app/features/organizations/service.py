"""组织模块服务层。

集中处理组织边界、成员资格、组织管理员判定，以及注册时的个人组织创建。
这些函数被多个模块复用，因此只依赖 models 与 shared，不依赖其它 feature 的路由层。

关键约定：
- 组织可见性判定统一走 require_organization_member，非成员返回 404 而不是 403，
  避免通过响应差异枚举组织存在性
- 组织负责人身份由 organization.owner_id 单一字段记录，成员行的 role 允许不再是
  owner，从而允许「先降级再转移负责人」的操作路径
- 成员移除前先检查其是否仍负责组织内项目，避免留下无主项目
"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.configuration import ModelConfiguration
from app.models.identity import Organization, OrganizationMember, User
from app.shared.errors import bad_request, forbidden, not_found
from app.shared.roles import (
    ORG_ADMIN_ROLES,
    ORG_ROLE_ADMIN,
    ORG_ROLE_OWNER,
    organization_role,
)


def personal_organization_name(user: User) -> str:
    """个人组织命名规则：与旧项目一致，如「zhangsan 的组织」。

    Args:
        user: 触发创建的用户。
    Returns:
        组织名称字符串，用户名超过 80 字符时截断。
    """
    return f"{(user.username or 'user')[:80]} 的组织"  # 用户名截断到 80 字符，避免撑爆 VARCHAR


def ensure_personal_organization(db: Session, user: User) -> Organization:
    """确保用户拥有个人组织；已存在时返回现有记录。

    注册事务中调用，失败时由调用方整体回滚。

    Args:
        db: 数据库会话。
        user: 待创建个人组织的用户。
    Returns:
        用户最早创建的组织（幂等，多次调用返回同一条）。
    """
    existing = (
        db.query(Organization)
        .filter(Organization.owner_id == user.id)
        .order_by(Organization.id)  # 取 ID 最小的，即最早创建的组织，保证幂等
        .first()
    )
    if existing is not None:
        return existing  # 幂等保护：已存在则直接复用

    organization = Organization(name=personal_organization_name(user), owner_id=user.id)
    db.add(organization)
    db.flush()  # 先 flush 拿到自增 ID，成员行才能引用
    db.add(
        OrganizationMember(
            organization_id=organization.id,
            user_id=user.id,
            role="owner",  # 用户自动是个人组织负责人
            agent_enabled=False,  # 默认不开启 Agent 能力
            allowed_model_ids=[],  # 默认不分配模型
        )
    )
    return organization


def require_organization_member(db: Session, organization_id: int, user: User) -> str:
    """验证当前用户属于指定组织；否则 404（隐藏组织存在性）。

    用 404 而不是 403 是为了避免通过响应差异枚举组织存在性；
    非平台管理员只能访问自己拥有的或作为成员加入的组织。

    Args:
        db: 数据库会话。
        organization_id: 目标组织 ID。
        user: 当前登录用户。
    Returns:
        该用户在组织内的有效角色字符串。
    """
    role = organization_role(db, organization_id, user)  # 内含 platform_admin 虚拟角色判定
    if role is None:
        raise not_found("组织不存在或无权访问")  # 错误信封映射：无权限与不存在共用 404
    return role


def require_organization_admin(db: Session, organization_id: int, user: User) -> str:
    """验证当前用户是组织管理员（owner / admin / platform_admin）。

    Args:
        db: 数据库会话。
        organization_id: 目标组织 ID。
        user: 当前登录用户。
    Returns:
        该用户在组织内的有效角色字符串。
    """
    role = require_organization_member(db, organization_id, user)  # 先判定成员资格
    if role not in ORG_ADMIN_ROLES:
        raise forbidden("需要组织管理员权限")  # 错误信封：是成员但权限不足
    return role


def get_organization_or_404(db: Session, organization_id: int) -> Organization:
    """按 ID 取组织，不存在时抛 404。

    与成员资格判定无关，只判定记录是否存在；权限校验请配合
    require_organization_member / require_organization_admin 使用。

    Args:
        db: 数据库会话。
        organization_id: 组织 ID。
    Returns:
        组织 ORM 实例。
    """
    organization = db.get(Organization, organization_id)
    if organization is None:
        raise not_found("组织不存在")  # 错误信封：真不存在
    return organization


def count_members(db: Session, organization_id: int) -> int:
    """统计组织当前成员总数，供列表页与响应体展示。

    Args:
        db: 数据库会话。
        organization_id: 组织 ID。
    Returns:
        成员行数；查询结果为 None 时兜底为 0。
    """
    return int(
        db.query(func.count(OrganizationMember.id))  # 用 func.count 直接在数据库侧聚合
        .filter(OrganizationMember.organization_id == organization_id)
        .scalar()
        or 0  # scalar() 在无记录时可能返回 None，统一兜底为 0
    )


def validate_allowed_model_ids(db: Session, allowed_model_ids: list[str]) -> list[str]:
    """校验被分配的模型均存在且处于启用状态；返回去重后的列表。

    去重使用 dict.fromkeys 保留原顺序，便于前端展示与 diff。

    Args:
        db: 数据库会话。
        allowed_model_ids: 前端提交的模型 domain_id 列表。
    Returns:
        去重且校验通过的模型 ID 列表。
    """
    deduped = list(dict.fromkeys(allowed_model_ids))  # 保序去重
    if not deduped:
        return []  # 空列表快速返回，避免发无意义的查询
    available = {
        row[0]
        for row in db.query(ModelConfiguration.domain_id)
        .filter(
            ModelConfiguration.domain_id.in_(deduped),  # 只在被提交的候选里查
            ModelConfiguration.is_enabled.is_(True),  # 只接受平台启用的模型
        )
        .all()
    }
    if available != set(deduped):
        raise bad_request("所分配模型不存在或已停用")  # 错误信封：模型 ID 无效或已停用
    return deduped


def upsert_member(
    db: Session,
    *,
    organization: Organization,
    member_user_id: int,
    requested_role: str,
    agent_enabled: bool,
    allowed_model_ids: list[str],
) -> OrganizationMember:
    """新增或更新组织成员。

    负责人降级规则：负责人身份由 organization.owner_id 决定，成员行的 role 不再
    被强制回写为 owner，因此管理员可以把原负责人降级为 admin 或 member。
    若仍试图把负责人直接降级为 member，会抛 forbidden，需要走「转移负责人」接口。

    Args:
        db: 数据库会话。
        organization: 目标组织。
        member_user_id: 目标成员用户 ID，需为启用账号。
        requested_role: 请求设置的组织角色。
        agent_enabled: 是否开启 Agent 能力。
        allowed_model_ids: 允许的模型 domain_id 列表；仅在 agent_enabled 为 True 时校验。
    Returns:
        新建或更新后的成员表行（尚未 commit）。
    """
    target = db.get(User, member_user_id)
    if target is None or not target.is_active:
        raise not_found("用户不存在或已停用")  # 错误信封：不允许加入停用/不存在的账号

    if target.id == organization.owner_id and requested_role not in (ORG_ROLE_OWNER, ORG_ROLE_ADMIN):
        # 负责人自保护：不能把 owner 直接降级为 member，需要走转移负责人流程
        raise forbidden("组织负责人至少需要组织管理员角色；如需转移负责人，请使用转移接口")

    # Agent 关闭时不校验模型（避免历史授权在 agent 关闭后仍报错），返回空列表覆盖
    allowed = validate_allowed_model_ids(db, allowed_model_ids) if agent_enabled else []

    row = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id == member_user_id,
        )
        .first()
    )
    if row is None:
        # 新建成员行；role/agent_enabled/allowed_model_ids 在下面统一赋值
        row = OrganizationMember(
            organization_id=organization.id,
            user_id=member_user_id,
        )
        db.add(row)
    row.role = requested_role  # 允许 owner 被降级为 admin 或 member
    row.agent_enabled = agent_enabled
    row.allowed_model_ids = allowed
    return row


def remove_member(db: Session, *, organization: Organization, member_user_id: int) -> None:
    """移除组织成员。

    负责人不能移除；仍负责组织内项目的成员不能移除，避免留下无主项目。

    Args:
        db: 数据库会话。
        organization: 目标组织。
        member_user_id: 待移除成员的用户 ID。
    """
    if organization.owner_id == member_user_id:
        raise forbidden("组织负责人不能移除")  # 自保护：负责人必须先转移再移除

    from app.models.project import Project  # 局部导入避免循环依赖

    owned = (
        db.query(Project.id)
        .filter(Project.organization_id == organization.id, Project.owner_id == member_user_id)
        .first()  # 只取一条即可判断是否有归属项目
    )
    if owned is not None:
        raise forbidden("该成员仍负责组织内项目，请先转移项目")  # 避免留下无主项目

    row = (
        db.query(OrganizationMember)
        .filter(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id == member_user_id,
        )
        .first()
    )
    if row is None:
        raise not_found("组织成员不存在")  # 错误信封：成员行本身不存在
    db.delete(row)  # 仅删除成员行；不会自动处理组织负责人（上面已拒绝）
