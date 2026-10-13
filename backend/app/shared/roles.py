"""跨模块角色判定：平台角色、组织角色、项目角色。

集中放在 shared，避免 feature 之间互相导入 service 造成循环依赖。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.identity import Organization, OrganizationMember, User
from app.models.project import Project, ProjectMember

# 平台级角色（对应 user.role 单值字段）：只有三档，不做继承或派生，
# 平台角色不自动授予任何组织/项目内的权限（除下面显式写出的「平台管理员视同负责人」）。
ROLE_PLATFORM_ADMIN = "admin"
ROLE_TEST = "test"
ROLE_DEV = "dev"
# 平台角色的合法取值集合，注册与改角色时用它做入参校验。
PLATFORM_ROLES = frozenset({ROLE_PLATFORM_ADMIN, ROLE_TEST, ROLE_DEV})

ROLE_LABELS: dict[str, str] = {
    "admin": "平台管理员",
    "test": "测试工程师",
    "dev": "开发工程师",
}

# 组织内角色：owner/admin 来自组织成员表，platform_admin 不入库，只在判定时临时返回。
ORG_ROLE_OWNER = "owner"
ORG_ROLE_ADMIN = "admin"
ORG_ROLE_MEMBER = "member"
ORG_ROLE_PLATFORM_ADMIN = "platform_admin"
# 组织管理端放行集合：owner、admin 以及平台管理员三档都可管理组织。
ORG_ADMIN_ROLES = frozenset({ORG_ROLE_OWNER, ORG_ROLE_ADMIN, ORG_ROLE_PLATFORM_ADMIN})
ORG_ROLE_LABELS: dict[str, str] = {
    ORG_ROLE_OWNER: "组织负责人",
    ORG_ROLE_ADMIN: "组织管理员",
    ORG_ROLE_MEMBER: "组织成员",
    ORG_ROLE_PLATFORM_ADMIN: "平台管理员",
}

# 项目内角色：0 最小、4 最大；等级数值只用于比较，不表示数量含义。
PROJECT_ROLE_VIEWER = "viewer"
PROJECT_ROLE_MEMBER = "member"
PROJECT_ROLE_EDITOR = "editor"
PROJECT_ROLE_OWNER = "owner"
PROJECT_ROLE_ADMIN = "admin"
PROJECT_ROLE_RANKS: dict[str, int] = {
    PROJECT_ROLE_VIEWER: 0,
    PROJECT_ROLE_MEMBER: 1,
    PROJECT_ROLE_EDITOR: 2,
    PROJECT_ROLE_OWNER: 3,
    PROJECT_ROLE_ADMIN: 4,
}
PROJECT_ROLE_LABELS: dict[str, str] = {
    PROJECT_ROLE_VIEWER: "只读成员",
    PROJECT_ROLE_MEMBER: "普通成员",
    PROJECT_ROLE_EDITOR: "项目管理员",
    PROJECT_ROLE_OWNER: "项目负责人",
    PROJECT_ROLE_ADMIN: "平台管理员",
}
# 项目内可以「被分配」的角色；owner 不可由成员表授予，platform_admin 也从不落库。
PROJECT_MEMBER_EDITABLE_ROLES = frozenset({PROJECT_ROLE_VIEWER, PROJECT_ROLE_MEMBER, PROJECT_ROLE_EDITOR})


def is_platform_admin(user: User) -> bool:
    """判断用户是否为平台管理员。

    Args:
        user: 当前请求用户。

    Returns:
        bool: user.role 等于 "admin" 时为 True。
    """
    # 平台角色是单值字段 user.role，不做任何继承或派生。
    return user.role == ROLE_PLATFORM_ADMIN


def can_access_admin(user: User) -> bool:
    """是否允许进入平台管理端。"""
    return is_platform_admin(user)


def require_org_role(db: Session, org_id: int, user: User, roles: frozenset[str]) -> None:
    """要求当前用户具备指定组织角色之一，否则抛 403。"""
    role = organization_role(db, org_id, user)
    if role is None or role not in roles:
        from app.shared.errors import forbidden

        raise forbidden("需要组织管理员权限")


def organization_role(db: Session, org_id: int, user: User) -> str | None:
    """返回用户在组织内的有效角色，非成员返回 None。"""
    if is_platform_admin(user):
        return ORG_ROLE_PLATFORM_ADMIN
    organization = db.get(Organization, org_id)
    if organization is None:
        return None
    if organization.owner_id == user.id:
        return ORG_ROLE_OWNER
    row = (
        db.query(OrganizationMember.role)
        .filter(OrganizationMember.organization_id == org_id, OrganizationMember.user_id == user.id)
        .first()
    )
    return row[0] if row else None


def is_organization_member(db: Session, org_id: int, user: User) -> bool:
    """用户是否属于该组织（任一有效角色算成员，含平台管理员）。"""
    return organization_role(db, org_id, user) is not None


def is_org_admin(db: Session, org_id: int, user: User) -> bool:
    """用户是否可管理该组织：平台管理员，或组织内 owner/admin。"""
    if is_platform_admin(user):
        return True
    return organization_role(db, org_id, user) in {ORG_ROLE_OWNER, ORG_ROLE_ADMIN}


def is_org_owner(db: Session, org_id: int, user: User) -> bool:
    """用户是否是该组织的创建负责人（organization.owner_id 命中）。

    与 is_org_admin 不同：组织成员表里的 admin 不算 owner，无法通过本判定。
    """
    organization = db.get(Organization, org_id)
    return organization is not None and organization.owner_id == user.id


def project_role_for(db: Session, project: Project, user: User) -> str | None:
    """返回用户在项目内的有效角色；无权访问时返回 None。

    与旧项目 ``accessible_project`` 的前置校验一致：项目归属于某个组织时，
    用户必须先是该组织成员，否则即使历史数据里残留了项目成员行也不授权。
    组织 owner/admin 在自己的组织里视同项目 owner。
    """
    if is_platform_admin(user):
        return PROJECT_ROLE_ADMIN
    if project.organization_id is not None and not is_organization_member(
        db, project.organization_id, user
    ):
        return None
    if project.owner_id == user.id:
        return PROJECT_ROLE_OWNER
    if project.organization_id is not None:
        org_role = organization_role(db, project.organization_id, user)
        if org_role in {ORG_ROLE_OWNER, ORG_ROLE_ADMIN}:
            return PROJECT_ROLE_OWNER
    row = (
        db.query(ProjectMember.role)
        .filter(ProjectMember.project_id == project.id, ProjectMember.user_id == user.id)
        .first()
    )
    if row is None:
        return None
    return normalize_project_role(row[0])


def normalize_project_role(role: str | None) -> str:
    """未登记的角色统一降级为 viewer，而不是按字面值放行。"""
    role = (role or "").strip().lower()
    return role if role in PROJECT_ROLE_RANKS else PROJECT_ROLE_VIEWER


def has_project_role(role: str | None, required: str) -> bool:
    """判断角色等级是否满足最低要求。"""
    if role is None:
        return False
    return PROJECT_ROLE_RANKS.get(normalize_project_role(role), -1) >= PROJECT_ROLE_RANKS.get(required, 99)


def can_manage_org(user: User, org: Organization, db: Session | None = None) -> bool:
    """判断用户是否可管理给定组织（与 is_org_admin 等价，但入参是实体而非 ID）。

    Args:
        user: 当前请求用户。
        org: 组织实体，直接读它的 owner_id 判定负责人身份。
        db: 数据库会话；为 None 时无法查组织成员表，仅能按内存字段判定。

    Returns:
        bool: 平台管理员、组织负责人、或组织成员表中的 owner/admin 返回 True；
        其余（包括 db 为 None 且前两项都不成立）一律返回 False。
    """
    if is_platform_admin(user):
        return True
    # 负责人身份直接来自 organization.owner_id，不需要会话即可判定。
    if org.owner_id == user.id:
        return True
    if db is None:
        # 未提供会话时无法查成员表，只按上面的内存判定，绝不假设放行。
        return False
    return organization_role(db, org.id, user) in {ORG_ROLE_OWNER, ORG_ROLE_ADMIN}


def accessible_organization_ids(db: Session, user: User) -> list[int] | None:
    """返回用户可见的组织 ID 列表；平台管理员返回 None 表示不过滤。"""
    if is_platform_admin(user):
        return None
    rows = (
        db.query(Organization.id)
        .outerjoin(OrganizationMember, OrganizationMember.organization_id == Organization.id)
        .filter(or_(Organization.owner_id == user.id, OrganizationMember.user_id == user.id))
        .distinct()
        .all()
    )
    return [row[0] for row in rows]


def accessible_project_ids(db: Session, user: User) -> list[int] | None:
    """返回用户可见的项目 ID 列表；平台管理员返回 None 表示不过滤。

    口径与旧项目 ``accessible_project_ids`` 一致，两个条件叠加：
    1. 组织边界：项目未绑定组织，或绑定的是用户所在的组织
    2. 项目内身份：项目 owner、项目成员、或项目所属组织的 owner/admin

    也就是说组织里的普通成员只能看到自己被分配（或自己负责）的项目，
    不会因为「在同一个组织」就自动看到组织内全部项目；而组织 owner/admin
    可以看到本组织的全部项目。历史残留的跨组织项目成员行不会生效。
    """
    if is_platform_admin(user):
        return None
    org_ids = accessible_organization_ids(db, user) or []
    rows = (
        db.query(Project.id)
        .outerjoin(
            ProjectMember,
            and_(
                ProjectMember.project_id == Project.id,
                ProjectMember.user_id == user.id,
            ),
        )
        .filter(
            or_(
                Project.organization_id.is_(None),
                Project.organization_id.in_(org_ids),
            )
        )
        .filter(
            or_(
                Project.owner_id == user.id,
                ProjectMember.id.isnot(None),
                Project.organization_id.in_(
                    db.query(OrganizationMember.organization_id).filter(
                        OrganizationMember.user_id == user.id,
                        OrganizationMember.role.in_([ORG_ROLE_OWNER, ORG_ROLE_ADMIN]),
                    )
                ),
            )
        )
        .distinct()
        .all()
    )
    return [row[0] for row in rows]
