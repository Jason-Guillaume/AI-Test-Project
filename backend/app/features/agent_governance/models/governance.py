"""平台级 Agent、Skill 与 MCP 接入配置。"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class AgentDefinition(Base):
    """由受控工作流模板构成的 Agent 配置。"""

    __tablename__ = "agent_definition"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(36), nullable=False, unique=True, index=True, comment="后端生成的稳定引用键")
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, default="", server_default=text("''"))
    workflow_template = Column(String(40), nullable=False, comment="受控的内置工作流模板")
    instruction = Column(Text, nullable=False, default="", server_default=text("''"))
    model_config_id = Column(Integer, ForeignKey("model_configuration.id", ondelete="SET NULL"), nullable=True)
    skill_keys = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    tool_keys = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    child_agent_ids = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    settings_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"), comment="运行配置与收尾提示词")
    triggers_json = Column(JSON, nullable=False, default=list, server_default=text("'[]'"), comment="事件触发配置")
    is_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"), index=True)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class AgentDefinitionRevision(Base):
    """Agent 每次保存的不可变配置快照。"""

    __tablename__ = "agent_definition_revision"
    __table_args__ = (UniqueConstraint("agent_definition_id", "version", name="uq_agent_definition_revision_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_definition_id = Column(Integer, ForeignKey("agent_definition.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    snapshot_json = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class SkillDefinition(Base):
    """可复用的 Markdown 指令 / 领域知识。"""

    __tablename__ = "skill_definition"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(36), nullable=False, unique=True, index=True, comment="后端生成的稳定引用键")
    name = Column(String(120), nullable=False)
    description = Column(Text, nullable=False, default="", server_default=text("''"))
    content = Column(Text, nullable=False)
    files_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"), comment="Skill 文件树，路径到 UTF-8 文本内容")
    mcp_tool_keys_json = Column(JSON, nullable=False, default=list, server_default=text("'[]'"), comment="加载 Skill 时关联的 MCP 工具")
    is_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"), index=True)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class SkillDefinitionRevision(Base):
    """Skill 每次保存的不可变内容快照。"""

    __tablename__ = "skill_definition_revision"
    __table_args__ = (UniqueConstraint("skill_definition_id", "version", name="uq_skill_definition_revision_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    skill_definition_id = Column(Integer, ForeignKey("skill_definition.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    snapshot_json = Column(JSON, nullable=False)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class MCPServer(Base):
    """MCP 服务登记；仅缓存发现结果，不自动授予工具执行权限。"""

    __tablename__ = "mcp_server"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(120), nullable=False)
    endpoint = Column(String(1000), nullable=False)
    auth_type = Column(String(20), nullable=False, default="none", server_default=text("'none'"))
    auth_secret_encrypted = Column(Text, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"), index=True)
    connection_status = Column(String(20), nullable=False, default="unknown", server_default=text("'unknown'"))
    discovered_tools_json = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    approved_tools_json = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    last_checked_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class ToolDefinitionOverride(Base):
    """平台内置工具允许管理员维护的说明覆写。"""

    __tablename__ = "agent_tool_definition_override"

    tool_key = Column(String(120), primary_key=True)
    description = Column(Text, nullable=False, default="", server_default=text("''"))
    parameter_overrides_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    is_enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    updated_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class SkillUsageEvent(Base):
    """任务创建时冻结的 Skill 使用记录，用于治理页统计。"""

    __tablename__ = "agent_skill_usage_event"

    id = Column(Integer, primary_key=True, autoincrement=True)
    skill_definition_id = Column(Integer, ForeignKey("skill_definition.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_definition_id = Column(Integer, ForeignKey("agent_definition.id", ondelete="SET NULL"), nullable=True, index=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
