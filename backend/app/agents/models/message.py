"""Agent 消息（AgentMessage）ORM 模型。

会话的消息历史：role（USER/ASSISTANT/SYSTEM）、message_type（TEXT/TEST_PLAN/
TEST_POINTS/TEST_CASES/EXECUTION/RESULT）、content（文本）、metadata_json
（结构化数据，发送前已脱敏，§20 不存完整敏感 prompt）。

Agent 模块专属表，由迁移 0007 显式建立；目录迁移保留既有表结构。
"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class AgentMessage(Base):
    """Agent 会话消息历史。metadata_json 仅存脱敏后的结构化数据。"""

    __tablename__ = "agent_message"
    __table_args__ = (
        Index("ix_agent_message_session_id", "session_id"),
        {"comment": "Agent 会话消息历史（metadata_json 存脱敏后的结构化数据）"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(
        Integer, ForeignKey("agent_session.id", ondelete="CASCADE"),
        nullable=False, comment="所属会话ID",
    )
    role = Column(
        String(20), nullable=False, default="USER", server_default=text("'USER'"),
        comment="消息角色：USER/ASSISTANT/SYSTEM",
    )
    message_type = Column(
        String(20), nullable=False, default="TEXT", server_default=text("'TEXT'"),
        comment="消息类型：TEXT/TEST_PLAN/TEST_POINTS/TEST_CASES/EXECUTION/RESULT",
    )
    content = Column(Text, nullable=True, comment="消息文本内容")
    metadata_json = Column(JSON, nullable=True, comment="结构化数据（已脱敏，不含敏感真实值）")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
