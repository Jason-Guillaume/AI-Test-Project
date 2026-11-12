"""Add recoverable deletion to test suites and plans."""

import sqlalchemy as sa
from alembic import op


revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("test_suite", "test_plan"):
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
        op.add_column(table, sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"))
        op.add_column(table, sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
        op.add_column(table, sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))
        op.create_foreign_key(
            "fk_soft_delete_deleted_by_user", table, "user", ["deleted_by"], ["id"], ondelete="SET NULL",
        )

    for table, name in (
        ("test_suite", "uq_test_suite_project_name"),
        ("test_plan", "uq_test_plan_project_name"),
    ):
        op.drop_constraint(name, table, type_="unique")
        op.create_index(
            name, table, ["project_id", "name"], unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )


def downgrade():
    for table, name in (
        ("test_plan", "uq_test_plan_project_name"),
        ("test_suite", "uq_test_suite_project_name"),
    ):
        op.drop_index(name, table_name=table)
        op.create_unique_constraint(name, table, ["project_id", "name"])

    for table in ("test_plan", "test_suite"):
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        op.drop_column(table, "deletion_batch_id")
        op.drop_column(table, "deletion_reason")
        op.drop_column(table, "deleted_by")
        op.drop_column(table, "deleted_at")
