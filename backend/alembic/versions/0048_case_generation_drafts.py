"""用例生成批次迁移。草稿表独立于 AgentSession。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "case_generation_batch",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("scope_node_id", sa.Integer(), sa.ForeignKey("test_scope_node.id", ondelete="SET NULL"), nullable=True),
        sa.Column("supervisor_agent_id", sa.Integer(), sa.ForeignKey("agent_definition.id", ondelete="SET NULL"), nullable=True),
        sa.Column("supervisor_version", sa.Integer(), nullable=False),
        sa.Column("supervisor_name", sa.String(120), nullable=False),
        sa.Column("model_config_id", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(200), nullable=True),
        sa.Column("requirements", sa.Text(), nullable=False),
        sa.Column("modules_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("review_summary", sa.Text(), nullable=True),
        sa.Column("review_gaps_json", sa.JSON(), nullable=False),
        sa.Column("module_errors_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=func.now()),
    )
    op.create_index("ix_case_generation_batch_project_id", "case_generation_batch", ["project_id"])
    op.create_table(
        "case_draft",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("batch_id", sa.Integer(), sa.ForeignKey("case_generation_batch.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module", sa.String(20), nullable=False),
        sa.Column("child_agent_id", sa.Integer(), sa.ForeignKey("agent_definition.id", ondelete="SET NULL"), nullable=True),
        sa.Column("child_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("child_name", sa.String(120), nullable=False, server_default=sa.text("''")),
        sa.Column("model_config_id", sa.Integer(), nullable=True),
        sa.Column("model_name", sa.String(200), nullable=True),
        sa.Column("skill_versions_json", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'PENDING'")),
        sa.Column("test_case_id", sa.Integer(), sa.ForeignKey("test_case.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=func.now()),
    )
    op.create_index("ix_case_draft_batch_id", "case_draft", ["batch_id"])
    op.create_index("ix_case_draft_status", "case_draft", ["status"])
    op.add_column("test_case", sa.Column("generation_batch_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_test_case_generation_batch",
        "test_case",
        "case_generation_batch",
        ["generation_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_test_case_generation_batch", "test_case", type_="foreignkey")
    op.drop_column("test_case", "generation_batch_id")
    op.drop_table("case_draft")
    op.drop_table("case_generation_batch")
