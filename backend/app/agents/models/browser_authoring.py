"""智能体浏览器探索会话与步骤的唯一 ORM 映射。"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database.base import Base


class WebAgentSession(Base):
    """智能体二轮受控浏览器会话；仅记录目标与预算，不执行任何正式用例。"""
    __tablename__ = "web_agent_session"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    environment_id = Column(Integer, ForeignKey("environment.id", ondelete="CASCADE"), nullable=False)
    auth_profile_id = Column(Integer, ForeignKey("web_auth_profile.id", ondelete="SET NULL"))
    base_url = Column(String(2000), nullable=False)
    target_page_path = Column(String(2000), nullable=False, default="", server_default="")
    status = Column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")
    step_budget = Column(Integer, nullable=False, default=20, server_default="20")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    closed_at = Column(DateTime)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="CASCADE"), nullable=True, index=True)
    task_agent_instance_id = Column(Integer, ForeignKey("task_agent_instance.id", ondelete="SET NULL"), nullable=True)
    agent_session_id = Column(Integer, ForeignKey("agent_session.id", ondelete="SET NULL"), nullable=True, index=True)

class WebAgentStep(Base):
    """智能体已执行步骤；步骤与结果加密落库，只有通过的步骤可提升为正式用例。"""
    __tablename__ = "web_agent_step"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("web_agent_session.id", ondelete="CASCADE"), nullable=False, index=True)
    sort = Column(Integer, nullable=False, default=0, server_default="0")
    step_encrypted = Column(Text, nullable=False)
    observation_encrypted = Column(Text)
    status = Column(String(16), nullable=False, default="PROPOSED", server_default="PROPOSED")
    source = Column(String(8), nullable=False, default="AI", server_default="AI")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
