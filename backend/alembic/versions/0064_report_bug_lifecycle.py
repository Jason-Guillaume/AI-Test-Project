"""Add recoverable deletion for reports and defects."""

import sqlalchemy as sa
from alembic import op


revision = "0064"
down_revision = "0063"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("test_report", "bug"):
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
        op.add_column(table, sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"))
        op.add_column(table, sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
        op.add_column(table, sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))
        op.create_foreign_key(
            "fk_soft_delete_deleted_by_user", table, "user", ["deleted_by"], ["id"], ondelete="SET NULL",
        )


def downgrade():
    for table in ("bug", "test_report"):
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        op.drop_column(table, "deletion_batch_id")
        op.drop_column(table, "deletion_reason")
        op.drop_column(table, "deleted_by")
        op.drop_column(table, "deleted_at")
