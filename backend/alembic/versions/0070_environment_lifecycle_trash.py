"""Add recoverable deletion to platform environment configurations."""

import sqlalchemy as sa
from alembic import op


revision = "0070"
down_revision = "0069"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("environment", sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
    op.add_column("environment", sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"))
    op.add_column("environment", sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
    op.add_column("environment", sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))
    op.create_foreign_key(
        "fk_soft_delete_deleted_by_user", "environment", "user", ["deleted_by"], ["id"], ondelete="SET NULL",
    )
    op.drop_index("ix_environment_name", table_name="environment")
    op.create_index(
        "ix_environment_name", "environment", ["name"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade():
    deleted_count = op.get_bind().execute(sa.text(
        "SELECT count(*) FROM environment WHERE deleted_at IS NOT NULL"
    )).scalar_one()
    if deleted_count:
        raise RuntimeError(
            "Cannot downgrade environment lifecycle while deleted environments remain; "
            "restore or permanently purge them first."
        )
    op.drop_index("ix_environment_name", table_name="environment")
    op.create_index("ix_environment_name", "environment", ["name"], unique=True)
    op.drop_constraint("fk_soft_delete_deleted_by_user", "environment", type_="foreignkey")
    op.drop_column("environment", "deletion_batch_id")
    op.drop_column("environment", "deletion_reason")
    op.drop_column("environment", "deleted_by")
    op.drop_column("environment", "deleted_at")
