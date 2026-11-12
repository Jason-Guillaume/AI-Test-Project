"""Add recoverable deletion and live-row uniqueness to Mock assets."""

import sqlalchemy as sa
from alembic import op


revision = "0067"
down_revision = "0066"
branch_labels = None
depends_on = None


_TABLES = ("mock_service", "mock_endpoint", "mock_scenario")


def upgrade():
    for table in _TABLES:
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
        op.add_column(table, sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"))
        op.add_column(table, sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
        op.add_column(table, sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))
        op.create_foreign_key(
            "fk_soft_delete_deleted_by_user", table, "user", ["deleted_by"], ["id"], ondelete="SET NULL",
        )

    op.drop_constraint("uq_mock_service_project_key", "mock_service", type_="unique")
    op.create_index(
        "uq_mock_service_project_key", "mock_service", ["project_id", "service_key"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_mock_endpoint_service_method_path", "mock_endpoint", type_="unique")
    op.create_index(
        "uq_mock_endpoint_service_method_path", "mock_endpoint",
        ["mock_service_id", "method", "path"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_mock_scenario_endpoint_key", "mock_scenario", type_="unique")
    op.create_index(
        "uq_mock_scenario_endpoint_key", "mock_scenario", ["mock_endpoint_id", "scenario_key"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("uq_mock_scenario_default", table_name="mock_scenario")
    op.create_index(
        "uq_mock_scenario_default", "mock_scenario", ["mock_endpoint_id"], unique=True,
        postgresql_where=sa.text("is_default = true AND deleted_at IS NULL"),
        sqlite_where=sa.text("is_default = true AND deleted_at IS NULL"),
    )


def downgrade():
    op.drop_index("uq_mock_scenario_default", table_name="mock_scenario")
    op.create_index(
        "uq_mock_scenario_default", "mock_scenario", ["mock_endpoint_id"], unique=True,
        postgresql_where=sa.text("is_default = true"), sqlite_where=sa.text("is_default = true"),
    )

    for index_name, table, columns in (
        ("uq_mock_scenario_endpoint_key", "mock_scenario", ["mock_endpoint_id", "scenario_key"]),
        ("uq_mock_endpoint_service_method_path", "mock_endpoint", ["mock_service_id", "method", "path"]),
        ("uq_mock_service_project_key", "mock_service", ["project_id", "service_key"]),
    ):
        op.drop_index(index_name, table_name=table)
        op.create_unique_constraint(index_name, table, columns)

    for table in reversed(_TABLES):
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        op.drop_column(table, "deletion_batch_id")
        op.drop_column(table, "deletion_reason")
        op.drop_column(table, "deleted_by")
        op.drop_column(table, "deleted_at")
