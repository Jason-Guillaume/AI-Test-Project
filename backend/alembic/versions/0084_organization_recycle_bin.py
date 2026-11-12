"""Add recoverable lifecycle fields to organizations."""

from alembic import op
import sqlalchemy as sa


revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organization", sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
    op.add_column(
        "organization",
        sa.Column(
            "deleted_by", sa.Integer(),
            sa.ForeignKey("user.id", name="fk_soft_delete_deleted_by_user", ondelete="SET NULL"),
            nullable=True, comment="删除操作人",
        ),
    )
    op.add_column("organization", sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
    op.add_column("organization", sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))


def downgrade() -> None:
    op.drop_column("organization", "deletion_batch_id")
    op.drop_column("organization", "deletion_reason")
    op.drop_column("organization", "deleted_by")
    op.drop_column("organization", "deleted_at")
