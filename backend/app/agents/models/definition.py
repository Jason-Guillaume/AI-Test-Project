"""归属当前能力包的唯一 ORM 模型定义。"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


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
