"""Agent 会话（AgentSession）ORM 模型。

记录会话所属项目、发起用户、当前工作流阶段及关联任务；入口据 current_stage
重建 AgentState 并跳过已完成环节（见 agents/workflows/legacy/state.py / graph.py）。

此 Agent 专属数据表由迁移 0007 显式建立；目录迁移保留既有表结构。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class AgentSession(Base):
    """共享的 Agent 对话上下文，供接口测试、安全分析和任务编排流程使用。"""

    __tablename__ = "agent_session"
    __table_args__ = (
        Index("ix_agent_session_project_status", "project_id", "status"),
        UniqueConstraint("task_run_id", name="uq_agent_session_task_run"),
        {"comment": "Agent 会话：记录项目、用户、工作流阶段及关联任务"},
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
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=True, index=True)
    task_agent_instance_id = Column(Integer, ForeignKey("task_agent_instance.id", ondelete="SET NULL"), nullable=True)
