"""Agent 会话（AgentSession）ORM 模型。

按 project + user 隔离。current_stage 记录工作流当前阶段，供下次请求重建
AgentState 时由入口 router 节点跳过已完成段（见 agent/state.py / graph.py）。

feature-local 表，由迁移 0007 显式建立。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.sql import func, text

from app.shared.database import Base


class AgentSession(Base):
    """接口测试 Agent 会话：一次对话式测试生成/执行/分析的上下文容器。"""

    __tablename__ = "agent_session"
    __table_args__ = (
        Index("ix_agent_session_project_status", "project_id", "status"),
        {"comment": "接口测试 Agent 会话：按 project+user 隔离，记录工作流阶段"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    user_id = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="发起会话的用户ID",
    )
    title = Column(String(200), nullable=True, comment="会话标题（首条消息摘要或用户命名）")
    status = Column(
        String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"),
        comment="会话状态：ACTIVE/COMPLETED/FAILED",
    )
    current_stage = Column(
        String(30), nullable=False, default="UNDERSTANDING",
        server_default=text("'UNDERSTANDING'"),
        comment="当前工作流阶段（见 AgentState.Stage）",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
