"""Track new parse strategies and queue wait times without rewriting history."""

from alembic import op
import sqlalchemy as sa

revision = "0099"
down_revision = "0098"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("knowledge_document_version", sa.Column("chunking_version", sa.String(40)))
    for table in ("knowledge_document_version", "knowledge_index_job"):
        op.add_column(table, sa.Column("queued_at", sa.DateTime(timezone=True)))
        # Existing queue entries have no known enqueue timestamp.
        op.alter_column(table, "queued_at", server_default=sa.func.now())


def downgrade():
    op.drop_column("knowledge_index_job", "queued_at")
    op.drop_column("knowledge_document_version", "queued_at")
    op.drop_column("knowledge_document_version", "chunking_version")
