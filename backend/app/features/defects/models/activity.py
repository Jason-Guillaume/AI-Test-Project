"""缺陷活动事件：状态动作、事实编辑、归档与外部反馈的统一审计记录。"""

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class BugActivity(Base):
    """一条缺陷活动事件；与状态变更在同一事务提交。"""

    __tablename__ = "bug_activity"
    __table_args__ = (
        Index("ix_bug_activity_project_action", "project_id", "action", "created_at"),
        {"comment": "缺陷动作与活动事件"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    bug_id = Column(
        Integer, ForeignKey("bug.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    project_id = Column(Integer, nullable=False, index=True)
    actor_id = Column(
        Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True,
    )
    actor_name = Column(String(100), nullable=True, comment="操作人姓名快照，外部来源为自报姓名")
    actor_type = Column(
        String(20), nullable=False, default="INTERNAL", server_default=text("'INTERNAL'"),
        comment="INTERNAL / EXTERNAL_SHARE / SYSTEM",
    )
    action = Column(String(30), nullable=False, comment="created/updated/confirm/ready_for_regression/regression_pass/regression_fail/reject/mark_duplicate/reopen/archive/restore/external_resolved")
    old_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=True)
    note = Column(Text, nullable=True, comment="操作说明")
    detail = Column(JSON, nullable=True, comment="附加上下文：反馈来源、验证执行、变更字段等")
    created_at = Column(DateTime, nullable=False, server_default=func.now())