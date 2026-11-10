"""用例生成审核闭环增量：审计表、草稿审核留痕、质量检查、原始内容与入库幂等。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None


def upgrade():
    # 草稿：审核留痕、质量检查结果、原始 AI 内容、入库失败原因。
    op.add_column("case_draft", sa.Column("original_payload_json", sa.JSON(), nullable=True))
    op.add_column("case_draft", sa.Column("quality_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")))
    op.add_column("case_draft", sa.Column("review_comment", sa.String(500), nullable=True))
    op.add_column("case_draft", sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True))
    op.add_column("case_draft", sa.Column("reviewed_at", sa.DateTime(), nullable=True))
    op.add_column("case_draft", sa.Column("import_error", sa.String(500), nullable=True))
    # 存量草稿的原始内容即当前内容。
    op.execute("UPDATE case_draft SET original_payload_json = payload_json WHERE original_payload_json IS NULL")
    op.alter_column("case_draft", "original_payload_json", nullable=False)
    # 一条草稿最多对应一条正式用例：并发入库由该部分唯一索引兜底。
    op.create_index(
        "uq_case_draft_test_case",
        "case_draft",
        ["test_case_id"],
        unique=True,
        postgresql_where=sa.text("test_case_id IS NOT NULL"),
    )
    # 批次：各模块生成耗时与 token 指标（不含提示词与密钥）。
    op.add_column(
        "case_generation_batch",
        sa.Column("module_metrics_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    # 审核与入库审计。
    op.create_table(
        "case_generation_audit",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("case_generation_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("case_draft.id", ondelete="CASCADE"), nullable=True),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=func.now()),
        comment="用例生成审核与入库操作审计",
    )
    op.create_index("ix_case_generation_audit_batch", "case_generation_audit", ["batch_id", "created_at"])
    op.create_index("ix_case_generation_audit_draft", "case_generation_audit", ["draft_id"])


def downgrade():
    op.drop_index("ix_case_generation_audit_draft", table_name="case_generation_audit")
    op.drop_index("ix_case_generation_audit_batch", table_name="case_generation_audit")
    op.drop_table("case_generation_audit")
    op.drop_column("case_generation_batch", "module_metrics_json")
    op.drop_index("uq_case_draft_test_case", table_name="case_draft")
    op.drop_column("case_draft", "import_error")
    op.drop_column("case_draft", "reviewed_at")
    op.drop_column("case_draft", "reviewed_by")
    op.drop_column("case_draft", "review_comment")
    op.drop_column("case_draft", "quality_json")
    op.drop_column("case_draft", "original_payload_json")
