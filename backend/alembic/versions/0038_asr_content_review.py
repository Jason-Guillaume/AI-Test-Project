"""新增独立内容评审任务和分块，不更改既有调参建议。"""

from alembic import op
import sqlalchemy as sa

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建队列、租约和分块表。"""
    op.create_table("asr_content_review_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("asr_job.id", ondelete="CASCADE"), nullable=False),
        sa.Column("comparison_id", sa.Integer(), sa.ForeignKey("asr_comparison.id", ondelete="CASCADE")),
        sa.Column("experiment_id", sa.Integer(), sa.ForeignKey("asr_experiment.id", ondelete="CASCADE")),
        sa.Column("model_config_id", sa.Integer(), sa.ForeignKey("model_configuration.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("review_type", sa.String(20), nullable=False),
        sa.Column("run_ids", sa.JSON(), nullable=False),
        sa.Column("primary_run_id", sa.Integer(), sa.ForeignKey("asr_model_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_artifact_ids", sa.JSON(), nullable=False),
        sa.Column("report_artifact_id", sa.Integer(), sa.ForeignKey("asr_evaluation_artifact.id", ondelete="SET NULL")),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("input_version", sa.String(40), nullable=False),
        sa.Column("model_revision", sa.String(64)),
        sa.Column("expected_runs", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"),
        sa.Column("coverage_status", sa.String(20), nullable=False, server_default="UNAVAILABLE"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_owner", sa.String(160)),
        sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)))
    for name in ("project_id", "job_id", "comparison_id", "experiment_id", "primary_run_id", "status"):
        op.create_index(f"ix_asr_content_review_job_{name}", "asr_content_review_job", [name])
    op.create_index("ix_asr_content_review_status_lease", "asr_content_review_job", ["status", "lease_expires_at"])
    op.create_table("asr_content_review_chunk",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("review_job_id", sa.Integer(), sa.ForeignKey("asr_content_review_job.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("scope", sa.JSON(), nullable=False),
        sa.Column("coverage_json", sa.JSON(), nullable=False),
        sa.Column("input_json", sa.JSON(), nullable=False),
        sa.Column("input_artifact_id", sa.Integer(), sa.ForeignKey("asr_evaluation_artifact.id", ondelete="SET NULL")),
        sa.Column("response_artifact_id", sa.Integer(), sa.ForeignKey("asr_evaluation_artifact.id", ondelete="SET NULL")),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="QUEUED"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text()),
        sa.UniqueConstraint("review_job_id", "ordinal", name="uq_asr_review_chunk_ordinal"))
    op.create_index("ix_asr_content_review_chunk_review_job_id", "asr_content_review_chunk", ["review_job_id"])


def downgrade() -> None:
    """删除内容评审任务及分块；产物文件保留供备份与人工清理。"""
    op.drop_table("asr_content_review_chunk")
    op.drop_table("asr_content_review_job")
