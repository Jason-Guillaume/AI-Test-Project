"""Add recoverable lifecycle fields to organizations."""

from alembic import op
import sqlalchemy as sa


revision = "0084"
down_revision = "0083"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns("organization")}
    columns = (
        sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"),
        sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"),
        sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"),
        sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"),
    )
    for column in columns:
        if column.name not in existing_columns:
            op.add_column("organization", column)

    foreign_keys = inspector.get_foreign_keys("organization")
    has_user_reference = any(
        fk.get("constrained_columns") == ["deleted_by"]
        and fk.get("referred_table") == "user"
        and fk.get("referred_columns") == ["id"]
        for fk in foreign_keys
    )
    if not has_user_reference:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("organization") as batch_op:
                batch_op.create_foreign_key(
                    "fk_soft_delete_deleted_by_user", "user", ["deleted_by"], ["id"], ondelete="SET NULL"
                )
        else:
            op.create_foreign_key(
                "fk_soft_delete_deleted_by_user", "organization", "user", ["deleted_by"], ["id"], ondelete="SET NULL"
            )


def downgrade() -> None:
    # This revision repairs deployments where older metadata-created schemas may already
    # contain any subset of these fields. Their ownership cannot be distinguished safely,
    # so downgrade deliberately retains the nullable columns and FK rather than risking
    # loss of existing soft-delete state. Re-upgrade remains idempotent.
    pass
