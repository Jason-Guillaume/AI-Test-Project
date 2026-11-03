"""建立 ASR 音频资产、夜间任务、对比复核及参数实验表。

本迁移只创建 ASR feature 自有表，不触碰平台核心模型和旧任务数据；回退时按外键依赖逆序删除。
"""

from alembic import op
import sqlalchemy as sa


revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    """显式创建 ASR 领域表，兼容已有库与空库的 0031 基线。"""
    op.create_table(
        "asr_audio",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url_ciphertext", sa.Text(), nullable=False),
        sa.Column("url_display", sa.String(500), nullable=False),
        sa.Column("duration_seconds", sa.Integer()),
        sa.Column("content_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("content_fingerprint", sa.String(64)),
        sa.Column("availability", sa.String(30), nullable=False, server_default="'UNKNOWN'"),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asr_audio_project_id", "asr_audio", ["project_id"])
    op.create_index("ix_asr_audio_project_created", "asr_audio", ["project_id", "created_at"])
    op.create_table(
        "asr_connection",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("role", sa.String(20), nullable=False),
        sa.Column("provider_id", sa.String(80), nullable=False, server_default="'generic-json'"),
        sa.Column("model_id", sa.String(160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("endpoint_ciphertext", sa.Text(), nullable=False),
        sa.Column("endpoint_display", sa.String(500), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False), sa.Column("secret_ciphertext", sa.Text()),
        sa.Column("secret_header", sa.String(100)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "name", "version", name="uq_asr_connection_project_name_version"),
    )
    op.create_index("ix_asr_connection_project_id", "asr_connection", ["project_id"])
    op.create_table(
        "asr_parameter_set",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("connection_id", sa.Integer(), sa.ForeignKey("asr_connection.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("definitions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("connection_id", "name", "version", name="uq_asr_parameter_set_version"),
    )
    op.create_index("ix_asr_parameter_set_project_id", "asr_parameter_set", ["project_id"])
    op.create_index("ix_asr_parameter_set_connection_id", "asr_parameter_set", ["connection_id"])
    op.create_table(
        "asr_schedule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False), sa.Column("audio_ids", sa.JSON(), nullable=False),
        sa.Column("connection_ids", sa.JSON(), nullable=False),
        sa.Column("parameter_set_id", sa.Integer(), sa.ForeignKey("asr_parameter_set.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("schedule_type", sa.String(20), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="'Asia/Shanghai'"),
        sa.Column("local_time", sa.String(8), nullable=False), sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_trigger_status", sa.String(40)), sa.Column("last_trigger_at", sa.DateTime(timezone=True)),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asr_schedule_project_id", "asr_schedule", ["project_id"])
    op.create_index("ix_asr_schedule_next_run_at", "asr_schedule", ["next_run_at"])
    op.create_table(
        "asr_job",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schedule_id", sa.Integer(), sa.ForeignKey("asr_schedule.id", ondelete="SET NULL")),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(40), nullable=False, server_default="'QUEUED'"),
        sa.Column("config_snapshot", sa.JSON(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("schedule_id", "scheduled_for", name="uq_asr_job_schedule_tick"),
    )
    op.create_index("ix_asr_job_project_id", "asr_job", ["project_id"])
    op.create_index("ix_asr_job_status", "asr_job", ["status"])
    op.create_index("ix_asr_job_project_created", "asr_job", ["project_id", "created_at"])
    op.create_table(
        "asr_model_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("asr_job.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_id", sa.Integer(), sa.ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("connection_id", sa.Integer(), sa.ForeignKey("asr_connection.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("parameter_set_id", sa.Integer(), sa.ForeignKey("asr_parameter_set.id", ondelete="RESTRICT")),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="'PENDING'"),
        sa.Column("remote_task_id", sa.String(500)), sa.Column("idempotency_key", sa.String(80), nullable=False, unique=True),
        sa.Column("submit_intent_at", sa.DateTime(timezone=True)),
        sa.Column("execution_ciphertext", sa.Text(), nullable=False), sa.Column("request_snapshot", sa.JSON(), nullable=False),
        sa.Column("transcript", sa.Text()), sa.Column("segments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error_message", sa.Text()), sa.Column("duration_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("job_id", "audio_id", "connection_id", name="uq_asr_run_job_audio_connection"),
    )
    for index_name, columns in (
        ("ix_asr_model_run_project_id", ["project_id"]), ("ix_asr_model_run_job_id", ["job_id"]),
        ("ix_asr_model_run_status", ["status"]), ("ix_asr_run_job_status", ["job_id", "status"]),
    ):
        op.create_index(index_name, "asr_model_run", columns)
    op.create_table(
        "asr_work_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("asr_model_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_owner", sa.String(160)), sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("run_id", name="uq_asr_work_run"),
    )
    op.create_index("ix_asr_work_available", "asr_work_item", ["available_at"])
    op.create_table(
        "asr_comparison",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("asr_job.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_id", sa.Integer(), sa.ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="'INCOMPLETE'"),
        sa.Column("algorithm_version", sa.String(40), nullable=False, server_default="'bounded-v1'"),
        sa.Column("degraded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("job_id", "audio_id", "version", name="uq_asr_comparison_version"),
    )
    op.create_index("ix_asr_comparison_project_id", "asr_comparison", ["project_id"])
    op.create_index("ix_asr_comparison_job_id", "asr_comparison", ["job_id"])
    op.create_table(
        "asr_diff_block",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("comparison_id", sa.Integer(), sa.ForeignKey("asr_comparison.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False), sa.Column("test_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("reference_a_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("reference_b_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("timing_source", sa.String(30), nullable=False, server_default="'UNAVAILABLE'"),
        sa.Column("timing_role", sa.String(20)),
        sa.Column("start_seconds", sa.Float()), sa.Column("end_seconds", sa.Float()),
        sa.Column("labels", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="'UNREVIEWED'"),
        sa.Column("confirmed_text", sa.Text()), sa.Column("review_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("comparison_id", "ordinal", name="uq_asr_diff_block_order"),
    )
    op.create_index("ix_asr_diff_block_comparison_id", "asr_diff_block", ["comparison_id"])
    op.create_table(
        "asr_review_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("block_id", sa.Integer(), sa.ForeignKey("asr_diff_block.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("confirmed_text", sa.Text()),
        sa.Column("include_reference_sample", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asr_review_audit_block_id", "asr_review_audit", ["block_id"])
    op.create_table(
        "asr_reference_sample",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_id", sa.Integer(), sa.ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("comparison_id", sa.Integer(), sa.ForeignKey("asr_comparison.id", ondelete="CASCADE"), nullable=False),
        sa.Column("block_id", sa.Integer(), sa.ForeignKey("asr_diff_block.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_version", sa.Integer(), nullable=False), sa.Column("review_version", sa.Integer(), nullable=False),
        sa.Column("confirmed_text", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("block_id", "review_version", name="uq_asr_reference_sample_review"),
    )
    op.create_index("ix_asr_reference_sample_project_id", "asr_reference_sample", ["project_id"])
    op.create_table(
        "asr_suggestion",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("comparison_id", sa.Integer(), sa.ForeignKey("asr_comparison.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_block_ids", sa.JSON(), nullable=False), sa.Column("observation", sa.Text(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False), sa.Column("parameter_path", sa.String(300)),
        sa.Column("current_value", sa.JSON()), sa.Column("candidate_value", sa.JSON()),
        sa.Column("rationale", sa.Text(), nullable=False), sa.Column("validation_steps", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="'DRAFT'"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asr_suggestion_project_id", "asr_suggestion", ["project_id"])
    op.create_index("ix_asr_suggestion_comparison_id", "asr_suggestion", ["comparison_id"])
    op.create_table(
        "asr_experiment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("comparison_id", sa.Integer(), sa.ForeignKey("asr_comparison.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("baseline_parameter_set_id", sa.Integer(), sa.ForeignKey("asr_parameter_set.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("candidate_parameters", sa.JSON(), nullable=False), sa.Column("change_summary", sa.Text(), nullable=False),
        sa.Column("reuse_reference_results", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="'DRAFT'"),
        sa.Column("candidate_job_id", sa.Integer(), sa.ForeignKey("asr_job.id", ondelete="SET NULL")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asr_experiment_project_id", "asr_experiment", ["project_id"])
    op.create_table(
        "asr_worker_heartbeat",
        sa.Column("worker_id", sa.String(160), primary_key=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade():
    """按外键依赖逆序删除 ASR 领域表；本操作不动现存音频文件或其他业务数据。"""
    op.drop_table("asr_worker_heartbeat")
    op.drop_index("ix_asr_experiment_project_id", table_name="asr_experiment")
    op.drop_table("asr_experiment")
    op.drop_index("ix_asr_suggestion_comparison_id", table_name="asr_suggestion")
    op.drop_index("ix_asr_suggestion_project_id", table_name="asr_suggestion")
    op.drop_table("asr_suggestion")
    op.drop_index("ix_asr_review_audit_block_id", table_name="asr_review_audit")
    op.drop_table("asr_review_audit")
    op.drop_index("ix_asr_reference_sample_project_id", table_name="asr_reference_sample")
    op.drop_table("asr_reference_sample")
    op.drop_index("ix_asr_diff_block_comparison_id", table_name="asr_diff_block")
    op.drop_table("asr_diff_block")
    op.drop_index("ix_asr_comparison_job_id", table_name="asr_comparison")
    op.drop_index("ix_asr_comparison_project_id", table_name="asr_comparison")
    op.drop_table("asr_comparison")
    op.drop_index("ix_asr_work_available", table_name="asr_work_item")
    op.drop_table("asr_work_item")
    op.drop_index("ix_asr_run_job_status", table_name="asr_model_run")
    op.drop_index("ix_asr_model_run_status", table_name="asr_model_run")
    op.drop_index("ix_asr_model_run_job_id", table_name="asr_model_run")
    op.drop_index("ix_asr_model_run_project_id", table_name="asr_model_run")
    op.drop_table("asr_model_run")
    op.drop_index("ix_asr_job_project_created", table_name="asr_job")
    op.drop_index("ix_asr_job_status", table_name="asr_job")
    op.drop_index("ix_asr_job_project_id", table_name="asr_job")
    op.drop_table("asr_job")
    op.drop_index("ix_asr_schedule_next_run_at", table_name="asr_schedule")
    op.drop_index("ix_asr_schedule_project_id", table_name="asr_schedule")
    op.drop_table("asr_schedule")
    op.drop_index("ix_asr_parameter_set_connection_id", table_name="asr_parameter_set")
    op.drop_index("ix_asr_parameter_set_project_id", table_name="asr_parameter_set")
    op.drop_table("asr_parameter_set")
    op.drop_index("ix_asr_connection_project_id", table_name="asr_connection")
    op.drop_table("asr_connection")
    op.drop_index("ix_asr_audio_project_created", table_name="asr_audio")
    op.drop_index("ix_asr_audio_project_id", table_name="asr_audio")
    op.drop_table("asr_audio")
