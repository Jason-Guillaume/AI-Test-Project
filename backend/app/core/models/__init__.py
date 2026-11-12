"""平台核心 ORM 模型注册入口。

仅注册历史基线中的九张平台表；Feature、Agent、Skill、MCP 与工具模型由各自包持有，
并由 Alembic 的上层装配显式发现，避免核心导入反向加载业务能力。
"""

from app.core.database.base import Base
from app.core.models.configuration import Environment, ModelConfiguration
from app.core.models.identity import Organization, OrganizationMember, User
from app.core.models.notification import Notification
from app.core.models.project import Project, ProjectMember, ProjectOutboundTarget

__all__ = [
    "Base",
    "User",
    "Organization",
    "OrganizationMember",
    "Project",
    "ProjectMember",
    "ProjectOutboundTarget",
    "ModelConfiguration",
    "Environment",
    "Notification",
]
