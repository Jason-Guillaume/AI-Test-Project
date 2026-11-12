"""Add recoverable deletion to Skill definitions."""

import sqlalchemy as sa
from alembic import op


revision = "0073"
down_revision = "0072"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"),
        sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"),
        sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"),
        sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"),
    ):
        op.add_column("skill_definition", column)
    op.create_foreign_key(
        "fk_soft_delete_deleted_by_user", "skill_definition", "user",
        ["deleted_by"], ["id"], ondelete="SET NULL",
    )


def downgrade():
    bind = op.get_bind()
    deleted_count = bind.execute(sa.text(
        "SELECT count(*) FROM skill_definition WHERE deleted_at IS NOT NULL"
    )).scalar_one()
    if deleted_count:
        raise RuntimeError(
            "Cannot downgrade Skill lifecycle while deleted definitions remain; "
            "restore them first."
        )
    op.drop_constraint("fk_soft_delete_deleted_by_user", "skill_definition", type_="foreignkey")
    for column in ("deletion_batch_id", "deletion_reason", "deleted_by", "deleted_at"):
        op.drop_column("skill_definition", column)
