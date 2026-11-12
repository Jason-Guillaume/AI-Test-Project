"""Add recoverable deletion to test strategies."""

import sqlalchemy as sa
from alembic import op


revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade():
    table = "test_strategy"
    op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
    op.add_column(table, sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"))
    op.add_column(table, sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
    op.add_column(table, sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))
    op.create_foreign_key(
        "fk_soft_delete_deleted_by_user", table, "user", ["deleted_by"], ["id"], ondelete="SET NULL",
    )
    op.drop_constraint("uq_test_strategy_project_name", table, type_="unique")
    op.create_index(
        "uq_test_strategy_project_name", table, ["project_id", "name"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade():
    table = "test_strategy"
    op.drop_index("uq_test_strategy_project_name", table_name=table)
    op.create_unique_constraint("uq_test_strategy_project_name", table, ["project_id", "name"])
    op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
    op.drop_column(table, "deletion_batch_id")
    op.drop_column(table, "deletion_reason")
    op.drop_column(table, "deleted_by")
    op.drop_column(table, "deleted_at")
