"""缺陷与测试执行或安全疑似问题的持久关联，不复制证据内容。"""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database.base import Base


class DefectSourceLink(Base):
    """记录一个人工确认的缺陷来源，来源删除时关联随之清理。"""

    __tablename__ = "defect_source_link"
    __table_args__ = (
        CheckConstraint("(case_execution_id IS NOT NULL AND security_finding_id IS NULL) OR (case_execution_id IS NULL AND security_finding_id IS NOT NULL)", name="ck_defect_source_exactly_one"),
        UniqueConstraint("bug_id", "case_execution_id", name="uq_defect_case_execution"),
        UniqueConstraint("bug_id", "security_finding_id", name="uq_defect_security_finding"),
        UniqueConstraint("project_id", "request_key", name="uq_defect_source_request"),
    )
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    bug_id = Column(Integer, ForeignKey("bug.id", ondelete="CASCADE"), nullable=False)
    case_execution_id = Column(Integer, ForeignKey("case_execution.id", ondelete="CASCADE"))
    security_finding_id = Column(Integer, ForeignKey("security_finding.id", ondelete="CASCADE"))
    request_key = Column(String(100))
    request_digest = Column(String(64))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())
