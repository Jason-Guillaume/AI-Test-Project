"""Agent 业务草稿版本与事务化保存回执。"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class BusinessAssemblyDraft(Base):
    """一次业务组装任务对应的可编辑草稿身份。"""

    __tablename__ = "business_assembly_draft"
    __table_args__ = (
        Index("ix_business_assembly_draft_project_updated", "project_id", "updated_at"),
        {"comment": "Agent 业务组装草稿身份"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    task_id = Column(Integer, ForeignKey("task.id", ondelete="SET NULL"), nullable=True, unique=True)
    task_run_id = Column(Integer, ForeignKey("task_run.id", ondelete="SET NULL"), nullable=True, unique=True)
    source_version_ids = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    current_revision = Column(Integer, nullable=False, default=1, server_default=text("1"))
    status = Column(String(24), nullable=False, default="EDITABLE", server_default=text("'EDITABLE'"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class BusinessAssemblyDraftRevision(Base):
    """不可变草稿修订；人工编辑和重新生成均追加新版本。"""

    __tablename__ = "business_assembly_draft_revision"
    __table_args__ = (
        UniqueConstraint("draft_id", "revision", name="uq_business_assembly_draft_revision"),
        {"comment": "业务组装草稿不可变修订"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(Integer, ForeignKey("business_assembly_draft.id", ondelete="CASCADE"), nullable=False, index=True)
    revision = Column(Integer, nullable=False)
    content_json = Column(JSON, nullable=False)
    validation_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    operation = Column(String(24), nullable=False, default="GENERATED", server_default=text("'GENERATED'"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class BusinessAssemblyApplication(Base):
    """业务保存幂等回执，记录确切修订与生成的正式流程 ID。"""

    __tablename__ = "business_assembly_application"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_business_assembly_application_key"),
        Index("ix_business_assembly_application_draft", "draft_id", "revision"),
        {"comment": "业务组装确认保存回执"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_id = Column(Integer, ForeignKey("business_assembly_draft.id", ondelete="CASCADE"), nullable=False)
    revision = Column(Integer, nullable=False)
    idempotency_key = Column(String(100), nullable=False)
    request_hash = Column(String(64), nullable=False)
    flow_ids = Column(JSON, nullable=False, default=list, server_default=text("'[]'"))
    applied_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
