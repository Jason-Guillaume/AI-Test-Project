"""归属当前能力包的唯一 ORM 模型定义。"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


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

class SkillUsageEvent(Base):
    """任务创建时冻结的 Skill 使用记录，用于治理页统计。"""

    __tablename__ = "agent_skill_usage_event"

    id = Column(Integer, primary_key=True, autoincrement=True)
    skill_definition_id = Column(Integer, ForeignKey("skill_definition.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_definition_id = Column(Integer, ForeignKey("agent_definition.id", ondelete="SET NULL"), nullable=True, index=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
