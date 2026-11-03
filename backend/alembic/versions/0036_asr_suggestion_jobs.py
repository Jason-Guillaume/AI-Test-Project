"""Persist idempotent ASR suggestion requests as background jobs."""

from alembic import op
import sqlalchemy as sa


revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asr_suggestion_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("comparison_id", sa.Integer(), sa.ForeignKey("asr_comparison.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_config_id", sa.Integer(), sa.ForeignKey("model_configuration.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("input_snapshot", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"),
        sa.Column("result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_message", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(160)),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("idempotency_key", name="uq_asr_suggestion_job_idempotency"),
    )
    op.create_index("ix_asr_suggestion_job_project_id", "asr_suggestion_job", ["project_id"])
    op.create_index("ix_asr_suggestion_job_comparison_id", "asr_suggestion_job", ["comparison_id"])
    op.create_index("ix_asr_suggestion_job_status", "asr_suggestion_job", ["status"])
    op.create_index("ix_asr_suggestion_job_status_lease", "asr_suggestion_job", ["status", "lease_expires_at"])


def downgrade() -> None:
    op.drop_index("ix_asr_suggestion_job_status_lease", table_name="asr_suggestion_job")
    op.drop_index("ix_asr_suggestion_job_status", table_name="asr_suggestion_job")
    op.drop_index("ix_asr_suggestion_job_comparison_id", table_name="asr_suggestion_job")
    op.drop_index("ix_asr_suggestion_job_project_id", table_name="asr_suggestion_job")
    op.drop_table("asr_suggestion_job")
