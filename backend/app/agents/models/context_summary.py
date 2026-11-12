"""带来源与内容指纹的会话摘要索引。"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func

from app.core.database.base import Base


class AgentSessionSummary(Base):
    """会话历史的提取式摘要；来源消息仍是唯一事实来源。"""

    __tablename__ = "agent_session_summary"

    session_id = Column(
        Integer, ForeignKey("agent_session.id", ondelete="CASCADE"), primary_key=True,
    )
    summary_version = Column(Integer, nullable=False, default=1)
    summary_kind = Column(String(24), nullable=False, default="EXTRACTIVE")
    summary_text = Column(Text, nullable=False)
    source_refs = Column(JSON, nullable=False, default=list)
    source_digest = Column(String(64), nullable=False)
    source_through_message_id = Column(Integer, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
