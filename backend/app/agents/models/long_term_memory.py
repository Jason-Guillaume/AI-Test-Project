"""按项目与 Agent 隔离、保留来源和版本的长期记忆。"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database.base import Base


class AgentLongTermMemory(Base):
    """不可覆盖的记忆版本；更新通过新增版本并将旧版本标为 SUPERSEDED。"""

    __tablename__ = "agent_long_term_memory"
    __table_args__ = (
        UniqueConstraint("project_id", "agent_definition_id", "memory_key", "version",
                         name="uq_agent_memory_key_version"),
        Index("ix_agent_memory_scope_status", "project_id", "agent_definition_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    agent_definition_id = Column(Integer, ForeignKey("agent_definition.id", ondelete="CASCADE"), nullable=False)
    memory_key = Column(String(160), nullable=False)
    version = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    source_refs = Column(JSON, nullable=False, default=list)
    source_digest = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default="ACTIVE")
    supersedes_id = Column(Integer, ForeignKey("agent_long_term_memory.id", ondelete="SET NULL"), nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
