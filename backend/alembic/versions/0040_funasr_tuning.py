"""Add API-bound FunASR ground truth and durable tuning sessions."""

from alembic import op
import sqlalchemy as sa


revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asr_api_binding",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("api_interface_id", sa.Integer(), sa.ForeignKey("api_interface.id", ondelete="SET NULL"), nullable=True),
        sa.Column("interface_version", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=True),
        sa.Column("environment_name", sa.String(100), nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("execution_ciphertext", sa.Text(), nullable=False),
        sa.Column("response_mapping", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), server_default="180", nullable=False),
        sa.Column("max_response_bytes", sa.Integer(), server_default="8000000", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_asr_api_binding_project_id", "asr_api_binding", ["project_id"])
    op.create_index("ix_asr_api_binding_api_interface_id", "asr_api_binding", ["api_interface_id"])
    op.create_index("ix_asr_api_binding_project", "asr_api_binding", ["project_id", "is_active"])

    op.create_table(
        "asr_ground_truth_version",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_id", sa.Integer(), sa.ForeignKey("asr_audio.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_version_id", sa.Integer(), sa.ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("raw_document", sa.JSON(), nullable=False),
        sa.Column("mapping_snapshot", sa.JSON(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("audio_version_id", "version", name="uq_asr_ground_truth_version"),
    )
    op.create_index("ix_asr_ground_truth_version_project_id", "asr_ground_truth_version", ["project_id"])
    op.create_index("ix_asr_ground_truth_version_audio_id", "asr_ground_truth_version", ["audio_id"])
    op.create_index("ix_asr_ground_truth_version_audio_version_id", "asr_ground_truth_version", ["audio_version_id"])
    op.create_index("ix_asr_ground_truth_audio_current", "asr_ground_truth_version", ["audio_id", "is_current"])

    op.create_table(
        "asr_tuning_session",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("binding_id", sa.Integer(), sa.ForeignKey("asr_api_binding.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("model_config_id", sa.Integer(), sa.ForeignKey("model_configuration.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(40), server_default="QUEUED", nullable=False),
        sa.Column("mode", sa.String(30), server_default="AUTO_TUNE", nullable=False),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("execution_ciphertext", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("current_round", sa.Integer(), server_default="1", nullable=False),
        sa.Column("best_round_id", sa.Integer(), nullable=True),
        sa.Column("max_rounds", sa.Integer(), nullable=False),
        sa.Column("max_asr_requests", sa.Integer(), nullable=False),
        sa.Column("asr_requests_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_ai_calls", sa.Integer(), nullable=False),
        sa.Column("ai_calls_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("no_improvement_limit", sa.Integer(), nullable=False),
        sa.Column("no_improvement_rounds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_items_limit", sa.Integer(), nullable=False),
        sa.Column("target_micro_cer", sa.Float(), nullable=True),
        sa.Column("min_improvement", sa.Float(), nullable=False),
        sa.Column("max_sample_degradation", sa.Float(), nullable=False),
        sa.Column("night_start", sa.String(5), server_default="22:00", nullable=False),
        sa.Column("night_end", sa.String(5), server_default="07:00", nullable=False),
        sa.Column("window_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(160), nullable=True),
        sa.Column("lease_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_requested", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("idempotency_key", name="uq_asr_tuning_session_idempotency"),
    )
    op.create_index("ix_asr_tuning_session_project_id", "asr_tuning_session", ["project_id"])
    op.create_index("ix_asr_tuning_session_binding_id", "asr_tuning_session", ["binding_id"])
    op.create_index("ix_asr_tuning_session_model_config_id", "asr_tuning_session", ["model_config_id"])
    op.create_index("ix_asr_tuning_session_status", "asr_tuning_session", ["status"])
    op.create_index("ix_asr_tuning_session_queue", "asr_tuning_session", ["status", "next_run_at"])
    op.create_index("ix_asr_tuning_session_project", "asr_tuning_session", ["project_id", "created_at"])

    op.create_table(
        "asr_tuning_round",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("asr_tuning_session.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), server_default="QUEUED", nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("parameter_hash", sa.String(64), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("report_json", sa.JSON(), nullable=True),
        sa.Column("report_markdown", sa.Text(), nullable=True),
        sa.Column("candidate_json", sa.JSON(), nullable=True),
        sa.Column("analysis_stage", sa.String(30), nullable=True),
        sa.Column("accepted", sa.Boolean(), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("session_id", "ordinal", name="uq_asr_tuning_round_ordinal"),
    )
    op.create_index("ix_asr_tuning_round_session_id", "asr_tuning_round", ["session_id"])
    op.create_index("ix_asr_tuning_round_status", "asr_tuning_round", ["session_id", "status"])

    op.create_table(
        "asr_tuning_item",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("asr_tuning_session.id", ondelete="CASCADE"), nullable=False),
        sa.Column("round_id", sa.Integer(), sa.ForeignKey("asr_tuning_round.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_id", sa.Integer(), sa.ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("audio_version_id", sa.Integer(), sa.ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ground_truth_version_id", sa.Integer(), sa.ForeignKey("asr_ground_truth_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), server_default="PENDING", nullable=False),
        sa.Column("idempotency_key", sa.String(80), nullable=False),
        sa.Column("response_received", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=True),
        sa.Column("normalized_json", sa.JSON(), nullable=True),
        sa.Column("ground_truth_json", sa.JSON(), nullable=True),
        sa.Column("answer_markdown", sa.Text(), nullable=True),
        sa.Column("response_markdown", sa.Text(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("review_json", sa.JSON(), nullable=True),
        sa.Column("review_status", sa.String(40), server_default="PENDING", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("submit_intent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("round_id", "audio_id", name="uq_asr_tuning_item_round_audio"),
        sa.UniqueConstraint("idempotency_key", name="uq_asr_tuning_item_idempotency"),
    )
    op.create_index("ix_asr_tuning_item_session_id", "asr_tuning_item", ["session_id"])
    op.create_index("ix_asr_tuning_item_round_id", "asr_tuning_item", ["round_id"])
    op.create_index("ix_asr_tuning_item_project_id", "asr_tuning_item", ["project_id"])
    op.create_index("ix_asr_tuning_item_status", "asr_tuning_item", ["status"])
    op.create_index("ix_asr_tuning_item_round_status", "asr_tuning_item", ["round_id", "status"])


def downgrade() -> None:
    op.drop_table("asr_tuning_item")
    op.drop_table("asr_tuning_round")
    op.drop_table("asr_tuning_session")
    op.drop_table("asr_ground_truth_version")
    op.drop_table("asr_api_binding")
