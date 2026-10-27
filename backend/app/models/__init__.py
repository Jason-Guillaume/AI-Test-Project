"""平台核心 ORM 模型集合。

普通导入本包只加载平台共享实体。业务 Feature 自有的 ORM 模型由所属 Feature 定义，不能加入
此基线包；数据库结构仍只通过 Alembic 管理。历史上从本包导出的 Feature 模型通过懒加载
兼容，避免普通导入时提前注册 Feature 表。
"""

from importlib import import_module

from app.shared.database import Base
# 这里只导入平台核心模型，供基线迁移与平台 Feature 复用。
# 业务 Feature 的专属表必须留在所属 Feature 的 models/ 包，并由显式 Alembic 迁移创建；
# 不要把 Bug、API Catalog、Agent Governance 等模型导入本包，否则会混入基线 create_all。
from app.models.configuration import Environment, ModelConfiguration
from app.models.identity import Organization, OrganizationMember, User
from app.models.notification import Notification
from app.models.project import Project, ProjectMember, ProjectOutboundTarget

# 保留旧公开名称；Feature 模型由下方 __getattr__ 按需加载，不进入核心模型导入链。
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
    "AgentDefinition",
    "AgentDefinitionRevision",
    "SkillDefinition",
    "SkillDefinitionRevision",
    "SkillUsageEvent",
    "MCPServer",
    "ToolDefinitionOverride",
    "ProjectEnvironment",
]

_FEATURE_MODEL_EXPORTS = {
    "AgentDefinition": ("app.features.agent_governance.models", "AgentDefinition"),
    "AgentDefinitionRevision": ("app.features.agent_governance.models", "AgentDefinitionRevision"),
    "MCPServer": ("app.features.agent_governance.models", "MCPServer"),
    "SkillDefinition": ("app.features.agent_governance.models", "SkillDefinition"),
    "SkillDefinitionRevision": ("app.features.agent_governance.models", "SkillDefinitionRevision"),
    "SkillUsageEvent": ("app.features.agent_governance.models", "SkillUsageEvent"),
    "ToolDefinitionOverride": ("app.features.agent_governance.models", "ToolDefinitionOverride"),
    "ProjectEnvironment": ("app.features.environment_configuration.models", "ProjectEnvironment"),
}


def __getattr__(name: str):
    """按需兼容旧的 ``from app.models import FeatureModel`` 导入。"""
    target = _FEATURE_MODEL_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
