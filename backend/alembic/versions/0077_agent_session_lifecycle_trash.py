"""Add recoverable deletion to user-managed Agent sessions."""

import sqlalchemy as sa
from alembic import op


revision = "0077"
down_revision = "0076"
branch_labels = None
depends_on = None


def upgrade():
    for column in (
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"),
        sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"),
        sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"),
        sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"),
    ):
        op.add_column("agent_session", column)
    op.create_foreign_key(
        "fk_soft_delete_deleted_by_user", "agent_session", "user",
        ["deleted_by"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_agent_session_deleted_at", "agent_session", ["deleted_at"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text(
        "SELECT count(*) FROM agent_session WHERE deleted_at IS NOT NULL"
    )).scalar_one():
        raise RuntimeError("Cannot downgrade Agent session lifecycle while deleted sessions remain; restore them first.")
    op.drop_index("ix_agent_session_deleted_at", table_name="agent_session")
    op.drop_constraint("fk_soft_delete_deleted_by_user", "agent_session", type_="foreignkey")
    for column in ("deletion_batch_id", "deletion_reason", "deleted_by", "deleted_at"):
        op.drop_column("agent_session", column)
