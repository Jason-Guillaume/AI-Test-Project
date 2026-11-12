"""Add recoverable deletion to project knowledge bases and documents."""

import sqlalchemy as sa
from alembic import op


revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("knowledge_base", "knowledge_document"):
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
        op.add_column(table, sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"))
        op.add_column(table, sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
        op.add_column(table, sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))
        op.create_foreign_key(
            "fk_soft_delete_deleted_by_user", table, "user", ["deleted_by"], ["id"], ondelete="SET NULL",
        )


def downgrade():
    bind = op.get_bind()
    deleted_count = bind.execute(sa.text(
        "SELECT (SELECT count(*) FROM knowledge_base WHERE deleted_at IS NOT NULL) + "
        "(SELECT count(*) FROM knowledge_document WHERE deleted_at IS NOT NULL)"
    )).scalar_one()
    if deleted_count:
        raise RuntimeError(
            "Cannot downgrade knowledge lifecycle while deleted bases or documents remain; "
            "restore or permanently purge them first."
        )
    for table in ("knowledge_document", "knowledge_base"):
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        for column in ("deletion_batch_id", "deletion_reason", "deleted_by", "deleted_at"):
            op.drop_column(table, column)
