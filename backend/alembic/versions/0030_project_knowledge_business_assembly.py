"""新增项目知识文档、解析队列、版本化业务草稿及保存回执。

Revision ID: 0030
Revises: 0029
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func, text

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    """显式创建知识库与业务组装 feature-local 表。"""
    op.add_column("task", sa.Column("business_assembly_json", sa.JSON(), nullable=True))

    op.create_table(
        "knowledge_base",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), server_default=text("'项目知识库'"), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_knowledge_base_project"),
        comment="项目业务知识库",
    )
    op.create_index("ix_knowledge_base_project_id", "knowledge_base", ["project_id"])

    op.create_table(
        "knowledge_document",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("knowledge_base_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=text("'ACTIVE'"), nullable=False),
        sa.Column("active_version_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_base.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        comment="项目知识文档逻辑身份",
    )
    op.create_index("ix_knowledge_document_knowledge_base_id", "knowledge_document", ["knowledge_base_id"])
    op.create_index("ix_knowledge_document_active_version_id", "knowledge_document", ["active_version_id"])
    op.create_index("ix_knowledge_document_base_status", "knowledge_document", ["knowledge_base_id", "status"])

    op.create_table(
        "knowledge_document_version",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=80), nullable=True),
        sa.Column("parser_version", sa.String(length=40), nullable=True),
        sa.Column("parse_status", sa.String(length=20), server_default=text("'PENDING'"), nullable=False),
        sa.Column("parse_error", sa.String(length=1000), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.Column("parsed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_knowledge_document_version_number"),
        comment="项目知识文档版本",
    )
    op.create_index("ix_knowledge_document_version_document_id", "knowledge_document_version", ["document_id"])
    op.create_index("ix_knowledge_document_version_status", "knowledge_document_version", ["parse_status", "created_at"])

    op.create_table(
        "knowledge_chunk",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_version_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading_path", sa.String(length=1000), nullable=True),
        sa.Column("locator", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["knowledge_document_version.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id", "ordinal", name="uq_knowledge_chunk_ordinal"),
        comment="项目知识文档正文分块",
    )
    op.create_index("ix_knowledge_chunk_document_version_id", "knowledge_chunk", ["document_version_id"])
    op.create_index("ix_knowledge_chunk_version_heading", "knowledge_chunk", ["document_version_id", "heading_path"])

    op.create_table(
        "knowledge_parse_job",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("document_version_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default=text("'PENDING'"), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=text("0"), nullable=False),
        sa.Column("available_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["document_version_id"], ["knowledge_document_version.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_version_id"),
        comment="项目知识文档持久化解析作业",
    )
    op.create_index("ix_knowledge_parse_job_queue", "knowledge_parse_job", ["status", "available_at", "id"])

    op.create_table(
        "business_assembly_draft",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("task_run_id", sa.Integer(), nullable=True),
        sa.Column("source_version_ids", sa.JSON(), server_default=text("'[]'"), nullable=False),
        sa.Column("current_revision", sa.Integer(), server_default=text("1"), nullable=False),
        sa.Column("status", sa.String(length=24), server_default=text("'EDITABLE'"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["task.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_run_id"], ["task_run.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
        sa.UniqueConstraint("task_run_id"),
        comment="Agent 业务组装草稿身份",
    )
    op.create_index("ix_business_assembly_draft_project_updated", "business_assembly_draft", ["project_id", "updated_at"])

    op.create_table(
        "business_assembly_draft_revision",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("validation_json", sa.JSON(), server_default=text("'{}'"), nullable=False),
        sa.Column("operation", sa.String(length=24), server_default=text("'GENERATED'"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["business_assembly_draft.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "revision", name="uq_business_assembly_draft_revision"),
        comment="业务组装草稿不可变修订",
    )
    op.create_index("ix_business_assembly_draft_revision_draft_id", "business_assembly_draft_revision", ["draft_id"])

    op.create_table(
        "business_assembly_application",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("flow_ids", sa.JSON(), server_default=text("'[]'"), nullable=False),
        sa.Column("applied_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
        sa.ForeignKeyConstraint(["draft_id"], ["business_assembly_draft.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["applied_by"], ["user.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_business_assembly_application_key"),
        comment="业务组装确认保存回执",
    )
    op.create_index("ix_business_assembly_application_draft", "business_assembly_application", ["draft_id", "revision"])


def downgrade():
    """按外键依赖逆序删除新增表与任务快照列。"""
    op.drop_index("ix_business_assembly_application_draft", table_name="business_assembly_application")
    op.drop_table("business_assembly_application")
    op.drop_index("ix_business_assembly_draft_revision_draft_id", table_name="business_assembly_draft_revision")
    op.drop_table("business_assembly_draft_revision")
    op.drop_index("ix_business_assembly_draft_project_updated", table_name="business_assembly_draft")
    op.drop_table("business_assembly_draft")
    op.drop_index("ix_knowledge_parse_job_queue", table_name="knowledge_parse_job")
    op.drop_table("knowledge_parse_job")
    op.drop_index("ix_knowledge_chunk_version_heading", table_name="knowledge_chunk")
    op.drop_index("ix_knowledge_chunk_document_version_id", table_name="knowledge_chunk")
    op.drop_table("knowledge_chunk")
    op.drop_index("ix_knowledge_document_version_status", table_name="knowledge_document_version")
    op.drop_index("ix_knowledge_document_version_document_id", table_name="knowledge_document_version")
    op.drop_table("knowledge_document_version")
    op.drop_index("ix_knowledge_document_base_status", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_active_version_id", table_name="knowledge_document")
    op.drop_index("ix_knowledge_document_knowledge_base_id", table_name="knowledge_document")
    op.drop_table("knowledge_document")
    op.drop_index("ix_knowledge_base_project_id", table_name="knowledge_base")
    op.drop_table("knowledge_base")
    op.drop_column("task", "business_assembly_json")
