"""Add recoverable deletion to test data assets and data providers."""

import sqlalchemy as sa
from alembic import op


revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("test_data_asset", "data_provider"):
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
        op.add_column(table, sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"))
        op.add_column(table, sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
        op.add_column(table, sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))
        op.create_foreign_key(
            "fk_soft_delete_deleted_by_user", table, "user", ["deleted_by"], ["id"], ondelete="SET NULL",
        )

    for name, table, cols in (
        ("uq_test_data_asset_project_name", "test_data_asset", ["project_id", "name"]),
        ("uq_data_provider_project_name", "data_provider", ["project_id", "name"]),
    ):
        op.drop_constraint(name, table, type_="unique")
        op.create_index(
            name, table, cols, unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"),
        )


def downgrade():
    for name, table, cols in (
        ("uq_data_provider_project_name", "data_provider", ["project_id", "name"]),
        ("uq_test_data_asset_project_name", "test_data_asset", ["project_id", "name"]),
    ):
        op.drop_index(name, table_name=table)
        op.create_unique_constraint(name, table, cols)

    for table in ("data_provider", "test_data_asset"):
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        op.drop_column(table, "deletion_batch_id")
        op.drop_column(table, "deletion_reason")
        op.drop_column(table, "deleted_by")
        op.drop_column(table, "deleted_at")
