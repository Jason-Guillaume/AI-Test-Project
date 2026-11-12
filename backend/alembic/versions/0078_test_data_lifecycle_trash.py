"""Add recoverable deletion to fixtures, pools, pool items, and DB connections."""

import sqlalchemy as sa
from alembic import op


revision = "0078"
down_revision = "0077"
branch_labels = None
depends_on = None

_TABLES = (
    "fixture",
    "data_pool",
    "data_pool_item",
    "target_database_connection",
)


def upgrade():
    for table in _TABLES:
        for column in (
            sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"),
            sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"),
            sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"),
            sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"),
        ):
            op.add_column(table, column)
        op.create_foreign_key(
            "fk_soft_delete_deleted_by_user", table, "user",
            ["deleted_by"], ["id"], ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])

    op.drop_constraint("uq_fixture_project_key", "fixture", type_="unique")
    op.drop_index("uq_fixture_global_key", table_name="fixture")
    op.create_index(
        "uq_fixture_project_key_live", "fixture", ["project_id", "fixture_key"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_fixture_global_key", "fixture", ["fixture_key"], unique=True,
        postgresql_where=sa.text("scope = 'GLOBAL' AND deleted_at IS NULL"),
    )

    op.drop_constraint("uq_data_pool_project_key", "data_pool", type_="unique")
    op.create_index(
        "uq_data_pool_project_key_live", "data_pool", ["project_id", "pool_key"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.drop_constraint("uq_target_db_conn", "target_database_connection", type_="unique")
    op.create_index(
        "uq_target_db_conn_live", "target_database_connection",
        ["project_id", "environment_id", "name"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade():
    bind = op.get_bind()
    duplicate_checks = (
        ("fixture", "project_id, fixture_key", "deleted_at IS NULL"),
        ("data_pool", "project_id, pool_key", "deleted_at IS NULL"),
        ("target_database_connection", "project_id, environment_id, name", "deleted_at IS NULL"),
    )
    for table, keys, predicate in duplicate_checks:
        duplicate = bind.execute(sa.text(
            f"SELECT 1 FROM {table} WHERE {predicate} GROUP BY {keys} HAVING count(*) > 1 LIMIT 1"
        )).first()
        if duplicate:
            raise RuntimeError(f"Cannot downgrade lifecycle for {table}: duplicate active keys exist")
    for table in _TABLES:
        if bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE deleted_at IS NOT NULL")).scalar_one():
            raise RuntimeError(f"Cannot downgrade {table} lifecycle while deleted records remain; restore them first")

    op.drop_index("uq_target_db_conn_live", table_name="target_database_connection")
    op.create_unique_constraint(
        "uq_target_db_conn", "target_database_connection", ["project_id", "environment_id", "name"],
    )
    op.drop_index("uq_data_pool_project_key_live", table_name="data_pool")
    op.create_unique_constraint("uq_data_pool_project_key", "data_pool", ["project_id", "pool_key"])
    op.drop_index("uq_fixture_global_key", table_name="fixture")
    op.drop_index("uq_fixture_project_key_live", table_name="fixture")
    op.create_unique_constraint("uq_fixture_project_key", "fixture", ["project_id", "fixture_key"])
    op.create_index(
        "uq_fixture_global_key", "fixture", ["fixture_key"], unique=True,
        postgresql_where=sa.text("scope = 'GLOBAL'"),
    )

    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_deleted_at", table_name=table)
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        for column in ("deletion_batch_id", "deletion_reason", "deleted_by", "deleted_at"):
            op.drop_column(table, column)
