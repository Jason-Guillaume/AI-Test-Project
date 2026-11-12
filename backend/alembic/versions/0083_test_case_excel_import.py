"""Add idempotent audit batches for Excel test-case imports."""

from alembic import op
import sqlalchemy as sa


revision = "0083"
down_revision = "0082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "test_case_import_batch",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_key", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("direction", sa.String(length=10), nullable=False),
        sa.Column("scope_node_id", sa.Integer(), sa.ForeignKey("test_scope_node.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("request_key", name="uq_test_case_import_request_key"),
        comment="测试用例 Excel 导入批次及幂等结果",
    )
    op.create_index("ix_test_case_import_project_created", "test_case_import_batch", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_test_case_import_project_created", table_name="test_case_import_batch")
    op.drop_table("test_case_import_batch")
