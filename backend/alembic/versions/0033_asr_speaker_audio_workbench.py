"""增加 ASR 音频版本、分段、独立处理任务及说话人工作台数据。

只创建 ASR 领域表并扩展 ASR 自有字段；已有历史任务仅在其固定版本与当前音频快照一致时回填，无法证明的旧链接保持未关联。
"""

from alembic import op
import sqlalchemy as sa
import json


revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def _backfill_current_audio_versions(connection) -> None:
    """为现有音频保存当前版本，并只关联有版本证据的历史运行、对比和校对样本。"""
    audios = connection.execute(sa.text(
        "SELECT id, content_version, name, url_ciphertext, url_display, duration_seconds, content_fingerprint, created_at "
        "FROM asr_audio"
    )).mappings().all()
    version_ids = {}
    for audio in audios:
        connection.execute(sa.text(
            "INSERT INTO asr_audio_version "
            "(audio_id, version, name, url_ciphertext, url_display, duration_seconds, content_fingerprint, created_at) "
            "VALUES (:audio_id, :version, :name, :url_ciphertext, :url_display, :duration_seconds, :fingerprint, :created_at)"
        ), {
            "audio_id": audio["id"], "version": audio["content_version"], "name": audio["name"],
            "url_ciphertext": audio["url_ciphertext"], "url_display": audio["url_display"],
            "duration_seconds": audio["duration_seconds"], "fingerprint": audio["content_fingerprint"],
            "created_at": audio["created_at"],
        })
        version_ids[(audio["id"], audio["content_version"])] = connection.execute(sa.text(
            "SELECT id FROM asr_audio_version WHERE audio_id=:audio_id AND version=:version"
        ), {"audio_id": audio["id"], "version": audio["content_version"]}).scalar_one()

    jobs = {}
    for row in connection.execute(sa.text("SELECT id, config_snapshot FROM asr_job")).mappings().all():
        snapshot = row["config_snapshot"] or {}
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except ValueError:
                snapshot = {}
        jobs[row["id"]] = snapshot if isinstance(snapshot, dict) else {}
    runs = connection.execute(sa.text("SELECT id, job_id, audio_id FROM asr_model_run")).mappings().all()
    run_versions = {}
    for run in runs:
        snapshot = jobs.get(run["job_id"], {})
        recorded = (snapshot.get("audio_versions") or {}).get(str(run["audio_id"]))
        version_id = version_ids.get((run["audio_id"], recorded))
        if version_id is not None:
            connection.execute(sa.text(
                "UPDATE asr_model_run SET audio_version_id=:version_id WHERE id=:run_id"
            ), {"version_id": version_id, "run_id": run["id"]})
            run_versions[run["id"]] = version_id

    for comparison in connection.execute(sa.text("SELECT id, job_id, audio_id FROM asr_comparison")).mappings().all():
        snapshot = jobs.get(comparison["job_id"], {})
        recorded = (snapshot.get("audio_versions") or {}).get(str(comparison["audio_id"]))
        version_id = version_ids.get((comparison["audio_id"], recorded))
        if version_id is not None:
            connection.execute(sa.text(
                "UPDATE asr_comparison SET audio_version_id=:version_id WHERE id=:comparison_id"
            ), {"version_id": version_id, "comparison_id": comparison["id"]})

    for sample in connection.execute(sa.text("SELECT id, audio_id, audio_version FROM asr_reference_sample")).mappings().all():
        version_id = version_ids.get((sample["audio_id"], sample["audio_version"]))
        if version_id is not None:
            connection.execute(sa.text(
                "UPDATE asr_reference_sample SET audio_version_id=:version_id WHERE id=:sample_id"
            ), {"version_id": version_id, "sample_id": sample["id"]})


def upgrade() -> None:
    """增加版本化工作台表、独立队列、说话人结果、关联与媒体分析摘要。"""
    with op.batch_alter_table("asr_connection") as batch:
        batch.alter_column("role", existing_type=sa.String(20), nullable=True)
        batch.add_column(sa.Column("task_type", sa.String(30), nullable=False, server_default="TRANSCRIPTION"))

    op.create_table(
        "asr_audio_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("audio_id", sa.Integer(), sa.ForeignKey("asr_audio.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False), sa.Column("name", sa.String(200), nullable=False),
        sa.Column("url_ciphertext", sa.Text(), nullable=False), sa.Column("url_display", sa.String(500), nullable=False),
        sa.Column("duration_seconds", sa.Integer()), sa.Column("content_fingerprint", sa.String(64)),
        sa.Column("source_info", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("audio_id", "version", name="uq_asr_audio_version"),
    )
    op.create_index("ix_asr_audio_version_audio_id", "asr_audio_version", ["audio_id"])
    with op.batch_alter_table("asr_model_run") as batch:
        batch.add_column(sa.Column("audio_version_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_asr_model_run_audio_version", "asr_audio_version",
            ["audio_version_id"], ["id"], ondelete="RESTRICT",
        )
    op.create_index("ix_asr_model_run_audio_version_id", "asr_model_run", ["audio_version_id"])
    with op.batch_alter_table("asr_comparison") as batch:
        batch.add_column(sa.Column("audio_version_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_asr_comparison_audio_version", "asr_audio_version",
            ["audio_version_id"], ["id"], ondelete="RESTRICT",
        )
    with op.batch_alter_table("asr_reference_sample") as batch:
        batch.add_column(sa.Column("audio_version_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_asr_reference_sample_audio_version", "asr_audio_version",
            ["audio_version_id"], ["id"], ondelete="RESTRICT",
        )
    for name in (
        "test_start_offset", "test_end_offset", "reference_a_start_offset", "reference_a_end_offset",
        "reference_b_start_offset", "reference_b_end_offset",
    ):
        op.add_column("asr_diff_block", sa.Column(name, sa.Integer(), nullable=True))

    op.create_table(
        "asr_transcript_segment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("asr_model_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_index", sa.Integer(), nullable=False), sa.Column("source_segment_id", sa.String(300)),
        sa.Column("text", sa.Text(), nullable=False), sa.Column("start_ms", sa.Integer()), sa.Column("end_ms", sa.Integer()),
        sa.Column("start_offset", sa.Integer()), sa.Column("end_offset", sa.Integer()),
        sa.Column("native_speaker_id", sa.String(200)), sa.Column("confidence", sa.Float()),
        sa.Column("channel", sa.String(100)), sa.Column("word_times", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("raw_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("model_run_id", "segment_index", name="uq_asr_transcript_segment_order"),
    )
    op.create_index("ix_asr_transcript_segment_model_run_id", "asr_transcript_segment", ["model_run_id"])
    op.create_index("ix_asr_transcript_segment_time", "asr_transcript_segment", ["model_run_id", "start_ms", "segment_index"])

    op.create_table(
        "asr_processing_run",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_id", sa.Integer(), sa.ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("audio_version_id", sa.Integer(), sa.ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_type", sa.String(30), nullable=False),
        sa.Column("connection_id", sa.Integer(), sa.ForeignKey("asr_connection.id", ondelete="RESTRICT")),
        sa.Column("retry_of_id", sa.Integer(), sa.ForeignKey("asr_processing_run.id", ondelete="SET NULL")),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("parameter_hash", sa.String(64), nullable=False), sa.Column("execution_ciphertext", sa.Text()),
        sa.Column("request_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(40), nullable=False, server_default="PENDING"),
        sa.Column("remote_task_id", sa.String(500)), sa.Column("submit_intent_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False), sa.Column("result_id", sa.Integer()),
        sa.Column("error_message", sa.Text()), sa.Column("duration_ms", sa.Integer()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    for name, columns in (
        ("ix_asr_processing_run_project_id", ["project_id"]), ("ix_asr_processing_run_status", ["status"]),
        ("ix_asr_processing_available", ["task_type", "status", "available_at"]),
        ("ix_asr_processing_audio", ["audio_version_id", "task_type", "created_at"]),
    ):
        op.create_index(name, "asr_processing_run", columns)
    op.create_table(
        "asr_processing_work_item",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("processing_run_id", sa.Integer(), sa.ForeignKey("asr_processing_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_owner", sa.String(160)), sa.Column("lease_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("processing_run_id", name="uq_asr_processing_work_run"),
    )
    op.create_index("ix_asr_processing_work_available", "asr_processing_work_item", ["available_at"])

    op.create_table(
        "asr_diarization_result",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_id", sa.Integer(), sa.ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("audio_version_id", sa.Integer(), sa.ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("processing_run_id", sa.Integer(), sa.ForeignKey("asr_processing_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("schema_version", sa.String(20), nullable=False, server_default="1.0"),
        sa.Column("timeline", sa.String(30), nullable=False, server_default="original_audio"),
        sa.Column("source_model_id", sa.String(160), nullable=False), sa.Column("source_model_version", sa.String(120)),
        sa.Column("raw_response", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("processing_run_id", name="uq_asr_diarization_processing_run"),
    )
    op.create_index("ix_asr_diarization_result_project_id", "asr_diarization_result", ["project_id"])
    op.create_index("ix_asr_diarization_result_audio_version_id", "asr_diarization_result", ["audio_version_id"])
    op.create_table(
        "asr_speaker",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("asr_diarization_result.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_label", sa.String(200), nullable=False), sa.Column("channel", sa.String(100)),
        sa.Column("display_name", sa.String(120), nullable=False), sa.Column("first_seen_ms", sa.Integer()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("result_id", "source_label", "channel", name="uq_asr_speaker_label_channel"),
    )
    op.create_index("ix_asr_speaker_result_id", "asr_speaker", ["result_id"])
    op.create_table(
        "asr_speaker_turn",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("result_id", sa.Integer(), sa.ForeignKey("asr_diarization_result.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False), sa.Column("stable_id", sa.String(120), nullable=False, unique=True),
        sa.Column("speaker_id", sa.Integer(), sa.ForeignKey("asr_speaker.id", ondelete="SET NULL")),
        sa.Column("source_speaker_id", sa.String(200)), sa.Column("start_ms", sa.Integer(), nullable=False),
        sa.Column("end_ms", sa.Integer(), nullable=False), sa.Column("text", sa.Text()),
        sa.Column("channel", sa.String(100)), sa.Column("confidence", sa.Float()),
        sa.Column("raw_payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint("result_id", "turn_index", name="uq_asr_speaker_turn_order"),
    )
    op.create_index("ix_asr_speaker_turn_result_id", "asr_speaker_turn", ["result_id"])
    op.create_index("ix_asr_speaker_turn_time", "asr_speaker_turn", ["result_id", "start_ms", "turn_index"])
    op.create_index("ix_asr_speaker_turn_speaker", "asr_speaker_turn", ["result_id", "speaker_id", "start_ms"])

    op.create_table(
        "asr_fusion_version",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("model_run_id", sa.Integer(), sa.ForeignKey("asr_model_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_version_id", sa.Integer(), sa.ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("diarization_result_id", sa.Integer(), sa.ForeignKey("asr_diarization_result.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="UNALIGNED"),
        sa.Column("algorithm_version", sa.String(40), nullable=False, server_default="time-overlap-v1"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("model_run_id", "diarization_result_id", "version", name="uq_asr_fusion_version"),
    )
    op.create_index("ix_asr_fusion_version_project_id", "asr_fusion_version", ["project_id"])
    op.create_index("ix_asr_fusion_run", "asr_fusion_version", ["model_run_id", "created_at"])
    op.create_table(
        "asr_speaker_assignment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fusion_version_id", sa.Integer(), sa.ForeignKey("asr_fusion_version.id", ondelete="CASCADE"), nullable=False),
        sa.Column("segment_id", sa.Integer(), sa.ForeignKey("asr_transcript_segment.id", ondelete="CASCADE")),
        sa.Column("speaker_turn_id", sa.Integer(), sa.ForeignKey("asr_speaker_turn.id", ondelete="CASCADE")),
        sa.Column("speaker_id", sa.Integer(), sa.ForeignKey("asr_speaker.id", ondelete="SET NULL")),
        sa.Column("start_offset", sa.Integer()), sa.Column("end_offset", sa.Integer()), sa.Column("coverage_ratio", sa.Float()),
        sa.Column("assignment_status", sa.String(30), nullable=False),
        sa.Column("source", sa.String(30), nullable=False, server_default="TIME_OVERLAP"),
        sa.Column("review_status", sa.String(20), nullable=False, server_default="UNREVIEWED"),
        sa.Column("review_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confirmed_speaker_id", sa.Integer(), sa.ForeignKey("asr_speaker.id", ondelete="SET NULL")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("fusion_version_id", "segment_id", "start_offset", "end_offset", "speaker_turn_id", name="uq_asr_speaker_assignment_span"),
    )
    op.create_index("ix_asr_speaker_assignment_fusion_version_id", "asr_speaker_assignment", ["fusion_version_id"])
    op.create_index("ix_asr_speaker_assignment_segment", "asr_speaker_assignment", ["fusion_version_id", "segment_id"])
    op.create_table(
        "asr_speaker_review_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("asr_speaker_assignment.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("speaker_id", sa.Integer(), sa.ForeignKey("asr_speaker.id", ondelete="SET NULL")),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("assignment_id", "version", name="uq_asr_speaker_review_version"),
    )
    op.create_index("ix_asr_speaker_review_audit_assignment_id", "asr_speaker_review_audit", ["assignment_id"])
    op.create_table(
        "asr_speaker_name_audit",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("speaker_id", sa.Integer(), sa.ForeignKey("asr_speaker.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("revision", sa.Integer(), nullable=False), sa.Column("previous_name", sa.String(120), nullable=False),
        sa.Column("next_name", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asr_speaker_name_audit_speaker_id", "asr_speaker_name_audit", ["speaker_id"])

    op.create_table(
        "asr_media_analysis",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("audio_version_id", sa.Integer(), sa.ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("processing_run_id", sa.Integer(), sa.ForeignKey("asr_processing_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("source", sa.String(50)),
        sa.Column("analyzer_version", sa.String(120)),
        sa.Column("source_info", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("original_format", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("analysis_pcm", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("signal_statistics", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("peaks", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("processed_range", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("warnings", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("analyzed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("processing_run_id", name="uq_asr_media_analysis_run"),
    )
    op.create_index("ix_asr_media_analysis_project_id", "asr_media_analysis", ["project_id"])
    op.create_index("ix_asr_media_analysis_audio", "asr_media_analysis", ["audio_version_id", "created_at"])
    _backfill_current_audio_versions(op.get_bind())


def downgrade() -> None:
    """按依赖逆序回退工作台新增表和音频版本引用。"""
    # 任务类型是新增数据；存在独立说话人连接时，降级会失去其类型语义，必须先由操作者处理这类资产。
    diarization_count = op.get_bind().execute(sa.text(
        "SELECT COUNT(*) FROM asr_connection WHERE task_type='DIARIZATION'"
    )).scalar_one()
    if diarization_count:
        raise RuntimeError("请先导出并删除说话人连接，再回退 0033")
    for table in (
        "asr_media_analysis", "asr_speaker_name_audit", "asr_speaker_review_audit", "asr_speaker_assignment",
        "asr_fusion_version", "asr_speaker_turn", "asr_speaker", "asr_diarization_result",
        "asr_processing_work_item", "asr_processing_run", "asr_transcript_segment",
    ):
        op.drop_table(table)
    with op.batch_alter_table("asr_reference_sample") as batch:
        batch.drop_constraint("fk_asr_reference_sample_audio_version", type_="foreignkey")
        batch.drop_column("audio_version_id")
    for name in (
        "test_start_offset", "test_end_offset", "reference_a_start_offset", "reference_a_end_offset",
        "reference_b_start_offset", "reference_b_end_offset",
    ):
        op.drop_column("asr_diff_block", name)
    op.drop_index("ix_asr_model_run_audio_version_id", table_name="asr_model_run")
    with op.batch_alter_table("asr_comparison") as batch:
        batch.drop_constraint("fk_asr_comparison_audio_version", type_="foreignkey")
        batch.drop_column("audio_version_id")
    with op.batch_alter_table("asr_model_run") as batch:
        batch.drop_constraint("fk_asr_model_run_audio_version", type_="foreignkey")
        batch.drop_column("audio_version_id")
    op.drop_table("asr_audio_version")
    with op.batch_alter_table("asr_connection") as batch:
        batch.drop_column("task_type")
        batch.alter_column("role", existing_type=sa.String(20), nullable=False)
