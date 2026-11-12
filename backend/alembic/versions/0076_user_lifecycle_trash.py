"""Add recoverable lifecycle fields to platform user accounts."""

import sqlalchemy as sa
from alembic import op


revision = "0076"
down_revision = "0075"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"),
        sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"),
        sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"),
        sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"),
    ):
        op.add_column("user", column)
    op.create_foreign_key(
        "fk_soft_delete_deleted_by_user", "user", "user",
        ["deleted_by"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_user_deleted_at", "user", ["deleted_at"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text(
        'SELECT count(*) FROM "user" WHERE deleted_at IS NOT NULL'
    )).scalar_one():
        raise RuntimeError("Cannot downgrade user lifecycle while deleted user accounts remain; restore them first.")
    op.drop_index("ix_user_deleted_at", table_name="user")
    op.drop_constraint("fk_soft_delete_deleted_by_user", "user", type_="foreignkey")
    for column in ("deletion_batch_id", "deletion_reason", "deleted_by", "deleted_at"):
        op.drop_column("user", column)
