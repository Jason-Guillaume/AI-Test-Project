"""Add recoverable deletion to project security strategies and mutation rules."""

import sqlalchemy as sa
from alembic import op


revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("security_strategy", "security_mutation_rule"):
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
        op.add_column(table, sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"))
        op.add_column(table, sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
        op.add_column(table, sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))
        op.create_foreign_key(
            "fk_soft_delete_deleted_by_user", table, "user", ["deleted_by"], ["id"], ondelete="SET NULL",
        )

    op.drop_constraint("uq_security_strategy_project_key", "security_strategy", type_="unique")
    op.drop_index("uq_security_strategy_system_key", table_name="security_strategy")
    op.create_index(
        "uq_security_strategy_project_key", "security_strategy", ["project_id", "strategy_key"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL AND deleted_at IS NULL"),
        sqlite_where=sa.text("project_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_security_strategy_system_key", "security_strategy", ["strategy_key"], unique=True,
        postgresql_where=sa.text("project_id IS NULL AND deleted_at IS NULL"),
        sqlite_where=sa.text("project_id IS NULL AND deleted_at IS NULL"),
    )


def downgrade():
    bind = op.get_bind()
    deleted_count = bind.execute(sa.text(
        "SELECT (SELECT count(*) FROM security_strategy WHERE deleted_at IS NOT NULL) + "
        "(SELECT count(*) FROM security_mutation_rule WHERE deleted_at IS NOT NULL)"
    )).scalar_one()
    if deleted_count:
        raise RuntimeError(
            "Cannot downgrade security lifecycle while deleted strategies or rules remain; "
            "restore or permanently purge them first."
        )
    op.drop_index("uq_security_strategy_system_key", table_name="security_strategy")
    op.drop_index("uq_security_strategy_project_key", table_name="security_strategy")
    op.create_unique_constraint(
        "uq_security_strategy_project_key", "security_strategy", ["project_id", "strategy_key"],
    )
    op.create_index(
        "uq_security_strategy_system_key", "security_strategy", ["strategy_key"], unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
        sqlite_where=sa.text("project_id IS NULL"),
    )
    for table in ("security_mutation_rule", "security_strategy"):
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        op.drop_column(table, "deletion_batch_id")
        op.drop_column(table, "deletion_reason")
        op.drop_column(table, "deleted_by")
        op.drop_column(table, "deleted_at")
