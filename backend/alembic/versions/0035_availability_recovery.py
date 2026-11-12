"""Track ASR worker readiness and preserve candidate rerun failure details."""

from alembic import op
import sqlalchemy as sa


revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asr_worker_heartbeat",
        sa.Column("business_ready", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("asr_experiment", sa.Column("failure_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("asr_experiment", "failure_reason")
    op.drop_column("asr_worker_heartbeat", "business_ready")
