"""Idempotency and audit record for Excel case imports."""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from app.core.database.base import Base


class TestCaseImportBatch(Base):
    __tablename__ = "test_case_import_batch"
    __table_args__ = (
        UniqueConstraint("request_key", name="uq_test_case_import_request_key"),
        Index("ix_test_case_import_project_created", "project_id", "created_at"),
        {"comment": "测试用例 Excel 导入批次及幂等结果"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    request_key = Column(String(36), nullable=False)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    direction = Column(String(10), nullable=False)
    scope_node_id = Column(Integer, ForeignKey("test_scope_node.id", ondelete="SET NULL"), nullable=True)
    source_hash = Column(String(64), nullable=False)
    result_json = Column(JSON, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
