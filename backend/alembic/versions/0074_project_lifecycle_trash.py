"""Add recoverable deletion to projects."""

import sqlalchemy as sa
from alembic import op


revision = "0074"
down_revision = "0073"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"),
        sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"),
        sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"),
        sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"),
    ):
        op.add_column("project", column)
    op.create_foreign_key(
        "fk_soft_delete_deleted_by_user", "project", "user",
        ["deleted_by"], ["id"], ondelete="SET NULL",
    )


def downgrade():
    bind = op.get_bind()
    deleted_count = bind.execute(sa.text(
        "SELECT count(*) FROM project WHERE deleted_at IS NOT NULL"
    )).scalar_one()
    if deleted_count:
        raise RuntimeError("Cannot downgrade Project lifecycle while deleted projects remain; restore them first.")
    op.drop_constraint("fk_soft_delete_deleted_by_user", "project", type_="foreignkey")
    for column in ("deletion_batch_id", "deletion_reason", "deleted_by", "deleted_at"):
        op.drop_column("project", column)
