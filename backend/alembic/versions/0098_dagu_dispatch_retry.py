"""Persist the next eligible Dagu dispatch attempt."""

from alembic import op
import sqlalchemy as sa

revision = "0098"
down_revision = "0097"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("automation_execution", sa.Column("dispatch_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("automation_execution", sa.Column("next_dispatch_at", sa.DateTime()))


def downgrade():
    op.drop_column("automation_execution", "next_dispatch_at")
    op.drop_column("automation_execution", "dispatch_attempts")
