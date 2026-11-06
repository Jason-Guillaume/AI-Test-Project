"""ASR 评测领域 ORM 模型。

本模块唯一持有音频、接口版本、参数方案、持久任务、运行租约、对比、复核、校对样本与实验模型；
由 ASR 服务、Worker 与 Alembic 显式协作。原始 URL 和执行凭据只保存密文，长响应限制在规范化文本及分段字段内。
"""

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class AsrAudio(Base):
    """项目内音频链接及其可追溯内容版本。"""

    __tablename__ = "asr_audio"
    __table_args__ = (Index("ix_asr_audio_project_created", "project_id", "created_at"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(200), nullable=False)
    url_ciphertext = Column(Text, nullable=False)
    url_display = Column(String(500), nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    content_version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    content_fingerprint = Column(String(64), nullable=True)
    availability = Column(String(30), nullable=False, default="UNKNOWN", server_default=text("'UNKNOWN'"))
    tags = Column(JSON, nullable=False, default=list)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AsrAudioVersion(Base):
    """不可变保存音频内容版本与脱敏来源，供运行、回听和分析共同引用。"""

    __tablename__ = "asr_audio_version"
    __table_args__ = (UniqueConstraint("audio_id", "version", name="uq_asr_audio_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    audio_id = Column(Integer, ForeignKey("asr_audio.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    name = Column(String(200), nullable=False)
    url_ciphertext = Column(Text, nullable=False)
    url_display = Column(String(500), nullable=False)
    duration_seconds = Column(Integer, nullable=True)
    content_fingerprint = Column(String(64), nullable=True)
    source_info = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrConnection(Base):
    """一个转写或说话人处理 HTTP 连接的不可变配置版本。"""

    __tablename__ = "asr_connection"
    __table_args__ = (UniqueConstraint("project_id", "name", "version", name="uq_asr_connection_project_name_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    role = Column(String(20), nullable=True)
    task_type = Column(String(30), nullable=False, default="TRANSCRIPTION", server_default=text("'TRANSCRIPTION'"))
    provider_id = Column(String(80), nullable=False, default="generic-json", server_default=text("'generic-json'"))
    model_id = Column(String(160), nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    endpoint_ciphertext = Column(Text, nullable=False)
    endpoint_display = Column(String(500), nullable=False)
    config_json = Column(JSON, nullable=False)
    secret_ciphertext = Column(Text, nullable=True)
    secret_header = Column(String(100), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AsrParameterSet(Base):
    """待测模型参数的不可变版本及其可验证定义。"""

    __tablename__ = "asr_parameter_set"
    __table_args__ = (UniqueConstraint("connection_id", "name", "version", name="uq_asr_parameter_set_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    connection_id = Column(Integer, ForeignKey("asr_connection.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    parameters = Column(JSON, nullable=False)
    definitions = Column(JSON, nullable=False, default=list)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrSchedule(Base):
    """一次性或每日重复的评测计划，按保存的音频和配置版本执行。"""

    __tablename__ = "asr_schedule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(160), nullable=False)
    audio_ids = Column(JSON, nullable=False)
    connection_ids = Column(JSON, nullable=False)
    parameter_set_id = Column(Integer, ForeignKey("asr_parameter_set.id", ondelete="RESTRICT"), nullable=False)
    schedule_type = Column(String(20), nullable=False)
    timezone = Column(String(80), nullable=False, default="Asia/Shanghai", server_default=text("'Asia/Shanghai'"))
    local_time = Column(String(8), nullable=False)
    scheduled_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True, index=True)
    last_trigger_status = Column(String(40), nullable=True)
    last_trigger_at = Column(DateTime(timezone=True), nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrJob(Base):
    """一次批量评测及其连接、参数和音频版本快照。"""

    __tablename__ = "asr_job"
    __table_args__ = (
        UniqueConstraint("schedule_id", "scheduled_for", name="uq_asr_job_schedule_tick"),
        Index("uq_asr_job_request_key", "request_key", unique=True),
        Index("ix_asr_job_project_created", "project_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    schedule_id = Column(Integer, ForeignKey("asr_schedule.id", ondelete="SET NULL"), nullable=True)
    scheduled_for = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(40), nullable=False, default="QUEUED", server_default=text("'QUEUED'"), index=True)
    config_snapshot = Column(JSON, nullable=False)
    request_key = Column(String(128), nullable=True)
    cancel_requested = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AsrModelRun(Base):
    """一次模型提交或轮询运行，保存幂等意图、响应文本与真实状态。"""

    __tablename__ = "asr_model_run"
    __table_args__ = (
        UniqueConstraint("job_id", "audio_id", "connection_id", name="uq_asr_run_job_audio_connection"),
        Index("ix_asr_run_job_status", "job_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("asr_job.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_id = Column(Integer, ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False)
    audio_version_id = Column(Integer, ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=True, index=True)
    connection_id = Column(Integer, ForeignKey("asr_connection.id", ondelete="RESTRICT"), nullable=False)
    parameter_set_id = Column(Integer, ForeignKey("asr_parameter_set.id", ondelete="RESTRICT"), nullable=True)
    role = Column(String(20), nullable=False)
    status = Column(String(40), nullable=False, default="PENDING", server_default=text("'PENDING'"), index=True)
    remote_task_id = Column(String(500), nullable=True)
    idempotency_key = Column(String(80), nullable=False, unique=True)
    submit_intent_at = Column(DateTime(timezone=True), nullable=True)
    execution_ciphertext = Column(Text, nullable=False)
    request_snapshot = Column(JSON, nullable=False)
    transcript = Column(Text, nullable=True)
    segments = Column(JSON, nullable=False, default=list)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AsrEvaluationArtifact(Base):
    """固定运行的产物元信息；正文存于受控持久卷，不进入列表响应。"""

    __tablename__ = "asr_evaluation_artifact"
    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("asr_job.id", ondelete="CASCADE"), nullable=False)
    run_id = Column(Integer, ForeignKey("asr_model_run.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(40), nullable=False)
    schema_version = Column(String(60), nullable=False)
    sha256 = Column(String(64), nullable=False)
    byte_size = Column(Integer, nullable=False)
    storage_key = Column(String(64), nullable=False, unique=True)
    status = Column(String(20), nullable=False, default="PENDING", index=True)
    source = Column(String(40), nullable=False)
    redaction_version = Column(String(40), nullable=True)
    redacted = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrWorkItem(Base):
    """可跨 Worker 恢复领取的短任务租约。"""

    __tablename__ = "asr_work_item"
    __table_args__ = (UniqueConstraint("run_id", name="uq_asr_work_run"), Index("ix_asr_work_available", "available_at"))

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("asr_model_run.id", ondelete="CASCADE"), nullable=False)
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lease_owner = Column(String(160), nullable=True)
    lease_generation = Column(Integer, nullable=False, default=0, server_default=text("0"))
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))


class AsrComparison(Base):
    """某次评测音频的三方对比版本与非准确率文本差异摘要。"""

    __tablename__ = "asr_comparison"
    __table_args__ = (UniqueConstraint("job_id", "audio_id", "version", name="uq_asr_comparison_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("asr_job.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_id = Column(Integer, ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False)
    audio_version_id = Column(Integer, ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    status = Column(String(30), nullable=False, default="INCOMPLETE", server_default=text("'INCOMPLETE'"))
    algorithm_version = Column(String(40), nullable=False, default="bounded-v1", server_default=text("'bounded-v1'"))
    degraded = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    summary = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrDiffBlock(Base):
    """对齐差异块及其带版本的人工确认状态。"""

    __tablename__ = "asr_diff_block"
    __table_args__ = (UniqueConstraint("comparison_id", "ordinal", name="uq_asr_diff_block_order"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    comparison_id = Column(Integer, ForeignKey("asr_comparison.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)
    test_text = Column(Text, nullable=False, default="")
    reference_a_text = Column(Text, nullable=False, default="")
    reference_b_text = Column(Text, nullable=False, default="")
    timing_source = Column(String(30), nullable=False, default="UNAVAILABLE", server_default=text("'UNAVAILABLE'"))
    timing_role = Column(String(20), nullable=True)
    start_seconds = Column(Float, nullable=True)
    end_seconds = Column(Float, nullable=True)
    test_start_offset = Column(Integer, nullable=True)
    test_end_offset = Column(Integer, nullable=True)
    reference_a_start_offset = Column(Integer, nullable=True)
    reference_a_end_offset = Column(Integer, nullable=True)
    reference_b_start_offset = Column(Integer, nullable=True)
    reference_b_end_offset = Column(Integer, nullable=True)
    labels = Column(JSON, nullable=False, default=list)
    review_status = Column(String(20), nullable=False, default="UNREVIEWED", server_default=text("'UNREVIEWED'"))
    confirmed_text = Column(Text, nullable=True)
    review_version = Column(Integer, nullable=False, default=0, server_default=text("0"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrReviewAudit(Base):
    """人工确认每一次变更的审计记录，包括确认空文本。"""

    __tablename__ = "asr_review_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    block_id = Column(Integer, ForeignKey("asr_diff_block.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    version = Column(Integer, nullable=False)
    review_status = Column(String(20), nullable=False)
    confirmed_text = Column(Text, nullable=True)
    include_reference_sample = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrReferenceSample(Base):
    """由人工明确确认并加入校对集的音频文本边界。"""

    __tablename__ = "asr_reference_sample"
    __table_args__ = (UniqueConstraint("block_id", "review_version", name="uq_asr_reference_sample_review"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_id = Column(Integer, ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False)
    comparison_id = Column(Integer, ForeignKey("asr_comparison.id", ondelete="CASCADE"), nullable=False)
    block_id = Column(Integer, ForeignKey("asr_diff_block.id", ondelete="CASCADE"), nullable=False)
    audio_version = Column(Integer, nullable=False)
    audio_version_id = Column(Integer, ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=True)
    review_version = Column(Integer, nullable=False)
    confirmed_text = Column(Text, nullable=False)
    reviewer_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrSuggestion(Base):
    """关联对比证据和已定义参数的候选调参建议。"""

    __tablename__ = "asr_suggestion"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    comparison_id = Column(Integer, ForeignKey("asr_comparison.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_block_ids = Column(JSON, nullable=False)
    observation = Column(Text, nullable=False)
    evidence = Column(Text, nullable=False)
    parameter_path = Column(String(300), nullable=True)
    current_value = Column(JSON, nullable=True)
    candidate_value = Column(JSON, nullable=True)
    rationale = Column(Text, nullable=False)
    validation_steps = Column(Text, nullable=False)
    status = Column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrSuggestionJob(Base):
    """Persistent, idempotent queue entry for potentially long ASR parameter suggestions."""

    __tablename__ = "asr_suggestion_job"
    __table_args__ = (
        Index("ix_asr_suggestion_job_status_lease", "status", "lease_expires_at"),
        UniqueConstraint("idempotency_key", name="uq_asr_suggestion_job_idempotency"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    comparison_id = Column(Integer, ForeignKey("asr_comparison.id", ondelete="CASCADE"), nullable=False, index=True)
    model_config_id = Column(Integer, ForeignKey("model_configuration.id", ondelete="RESTRICT"), nullable=False)
    idempotency_key = Column(String(64), nullable=False)
    input_snapshot = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="QUEUED", server_default=text("'QUEUED'"), index=True)
    result_json = Column(JSON, nullable=False, default=dict, server_default=text("'{}'"))
    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    lease_owner = Column(String(160), nullable=True)
    lease_generation = Column(Integer, nullable=False, default=0, server_default=text("0"))
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    requested_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AsrContentReviewJob(Base):
    """独立内容评审任务，不复用人工确认后的调参建议合同。"""
    __tablename__ = "asr_content_review_job"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_asr_content_review_key"),
                      Index("ix_asr_content_review_status_lease", "status", "lease_expires_at"))
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("asr_job.id", ondelete="CASCADE"), nullable=False, index=True)
    comparison_id = Column(Integer, ForeignKey("asr_comparison.id", ondelete="CASCADE"), nullable=True, index=True)
    experiment_id = Column(Integer, ForeignKey("asr_experiment.id", ondelete="CASCADE"), nullable=True, index=True)
    model_config_id = Column(Integer, ForeignKey("model_configuration.id", ondelete="RESTRICT"), nullable=False)
    review_type = Column(String(20), nullable=False)
    run_ids = Column(JSON, nullable=False)
    primary_run_id = Column(Integer, ForeignKey("asr_model_run.id", ondelete="CASCADE"), nullable=False, index=True)
    source_artifact_ids = Column(JSON, nullable=False, default=list)
    report_artifact_id = Column(Integer, ForeignKey("asr_evaluation_artifact.id", ondelete="SET NULL"), nullable=True)
    idempotency_key = Column(String(64), nullable=False)
    input_version = Column(String(40), nullable=False)
    model_revision = Column(String(64), nullable=True)
    expected_runs = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False, default="QUEUED", server_default=text("'QUEUED'"), index=True)
    coverage_status = Column(String(20), nullable=False, default="UNAVAILABLE", server_default=text("'UNAVAILABLE'"))
    cancel_requested = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    requested_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    lease_owner = Column(String(160), nullable=True)
    lease_generation = Column(Integer, nullable=False, default=0, server_default=text("0"))
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AsrContentReviewChunk(Base):
    """冻结的评审块和独立阶段状态，失败重试不重新识别。"""
    __tablename__ = "asr_content_review_chunk"
    __table_args__ = (UniqueConstraint("review_job_id", "ordinal", name="uq_asr_review_chunk_ordinal"),)
    id = Column(Integer, primary_key=True)
    review_job_id = Column(Integer, ForeignKey("asr_content_review_job.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)
    scope = Column(JSON, nullable=False)
    coverage_json = Column(JSON, nullable=False, default=list)
    input_json = Column(JSON, nullable=False)
    input_artifact_id = Column(Integer, ForeignKey("asr_evaluation_artifact.id", ondelete="SET NULL"), nullable=True)
    response_artifact_id = Column(Integer, ForeignKey("asr_evaluation_artifact.id", ondelete="SET NULL"), nullable=True)
    result_json = Column(JSON, nullable=False, default=dict)
    status = Column(String(32), nullable=False, default="QUEUED", server_default=text("'QUEUED'"))
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    error_message = Column(Text, nullable=True)


class AsrExperiment(Base):
    """基线与候选参数实验草稿，执行时新建任务而不覆盖基线。"""

    __tablename__ = "asr_experiment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    comparison_id = Column(Integer, ForeignKey("asr_comparison.id", ondelete="RESTRICT"), nullable=False)
    baseline_parameter_set_id = Column(Integer, ForeignKey("asr_parameter_set.id", ondelete="RESTRICT"), nullable=False)
    candidate_parameters = Column(JSON, nullable=False)
    change_summary = Column(Text, nullable=False)
    reuse_reference_results = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    status = Column(String(20), nullable=False, default="DRAFT", server_default=text("'DRAFT'"))
    candidate_job_id = Column(Integer, ForeignKey("asr_job.id", ondelete="SET NULL"), nullable=True)
    failure_reason = Column(Text, nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrWorkerHeartbeat(Base):
    """独立 ASR Worker 的最近心跳信息。"""

    __tablename__ = "asr_worker_heartbeat"

    worker_id = Column(String(160), primary_key=True)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    active_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    business_ready = Column(Boolean, nullable=False, default=False, server_default=text("false"))


class AsrTranscriptSegment(Base):
    """从原始 ASR 响应规范化出的稳定片段，偏移按 Python Unicode code point 计数。"""

    __tablename__ = "asr_transcript_segment"
    __table_args__ = (
        UniqueConstraint("model_run_id", "segment_index", name="uq_asr_transcript_segment_order"),
        Index("ix_asr_transcript_segment_time", "model_run_id", "start_ms", "segment_index"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    model_run_id = Column(Integer, ForeignKey("asr_model_run.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_index = Column(Integer, nullable=False)
    source_segment_id = Column(String(300), nullable=True)
    text = Column(Text, nullable=False)
    start_ms = Column(Integer, nullable=True)
    end_ms = Column(Integer, nullable=True)
    start_offset = Column(Integer, nullable=True)
    end_offset = Column(Integer, nullable=True)
    native_speaker_id = Column(String(200), nullable=True)
    confidence = Column(Float, nullable=True)
    channel = Column(String(100), nullable=True)
    word_times = Column(JSON, nullable=False, default=list)
    raw_payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrProcessingRun(Base):
    """可独立恢复的说话人或媒体分析阶段，拥有自己的快照、期限与结果版本。"""

    __tablename__ = "asr_processing_run"
    __table_args__ = (
        Index("ix_asr_processing_available", "task_type", "status", "available_at"),
        Index("ix_asr_processing_audio", "audio_version_id", "task_type", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_id = Column(Integer, ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False)
    audio_version_id = Column(Integer, ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False)
    task_type = Column(String(30), nullable=False)
    connection_id = Column(Integer, ForeignKey("asr_connection.id", ondelete="RESTRICT"), nullable=True)
    retry_of_id = Column(Integer, ForeignKey("asr_processing_run.id", ondelete="SET NULL"), nullable=True)
    parameters = Column(JSON, nullable=False, default=dict)
    parameter_hash = Column(String(64), nullable=False)
    execution_ciphertext = Column(Text, nullable=True)
    request_snapshot = Column(JSON, nullable=False, default=dict)
    status = Column(String(40), nullable=False, default="PENDING", server_default=text("'PENDING'"), index=True)
    remote_task_id = Column(String(500), nullable=True)
    submit_intent_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deadline_at = Column(DateTime(timezone=True), nullable=False)
    result_id = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AsrProcessingWorkItem(Base):
    """说话人及媒体任务的独立租约，避免阶段重试触碰三方 ASR 工作项。"""

    __tablename__ = "asr_processing_work_item"
    __table_args__ = (
        UniqueConstraint("processing_run_id", name="uq_asr_processing_work_run"),
        Index("ix_asr_processing_work_available", "available_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    processing_run_id = Column(Integer, ForeignKey("asr_processing_run.id", ondelete="CASCADE"), nullable=False)
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lease_owner = Column(String(160), nullable=True)
    lease_generation = Column(Integer, nullable=False, default=0, server_default=text("0"))
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))


class AsrDiarizationResult(Base):
    """一个不可变说话人结果版本，保留标准协议、原始响应和模型快照。"""

    __tablename__ = "asr_diarization_result"
    __table_args__ = (UniqueConstraint("processing_run_id", name="uq_asr_diarization_processing_run"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_id = Column(Integer, ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False)
    audio_version_id = Column(Integer, ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False, index=True)
    processing_run_id = Column(Integer, ForeignKey("asr_processing_run.id", ondelete="CASCADE"), nullable=False)
    schema_version = Column(String(20), nullable=False, default="1.0", server_default=text("'1.0'"))
    timeline = Column(String(30), nullable=False, default="original_audio", server_default=text("'original_audio'"))
    source_model_id = Column(String(160), nullable=False)
    source_model_version = Column(String(120), nullable=True)
    raw_response = Column(JSON, nullable=False, default=dict)
    warnings = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrSpeaker(Base):
    """只在单个说话人结果内有效的标签与人工显示名，不表示真实身份。"""

    __tablename__ = "asr_speaker"
    __table_args__ = (UniqueConstraint("result_id", "source_label", "channel", name="uq_asr_speaker_label_channel"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    result_id = Column(Integer, ForeignKey("asr_diarization_result.id", ondelete="CASCADE"), nullable=False, index=True)
    source_label = Column(String(200), nullable=False)
    channel = Column(String(100), nullable=True)
    display_name = Column(String(120), nullable=False)
    first_seen_ms = Column(Integer, nullable=True)
    revision = Column(Integer, nullable=False, default=0, server_default=text("0"))


class AsrSpeakerTurn(Base):
    """真实说话人时间区间；允许未知说话人和同时间重叠，不重排原生顺序。"""

    __tablename__ = "asr_speaker_turn"
    __table_args__ = (
        UniqueConstraint("result_id", "turn_index", name="uq_asr_speaker_turn_order"),
        Index("ix_asr_speaker_turn_time", "result_id", "start_ms", "turn_index"),
        Index("ix_asr_speaker_turn_speaker", "result_id", "speaker_id", "start_ms"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    result_id = Column(Integer, ForeignKey("asr_diarization_result.id", ondelete="CASCADE"), nullable=False, index=True)
    turn_index = Column(Integer, nullable=False)
    stable_id = Column(String(120), nullable=False, unique=True)
    speaker_id = Column(Integer, ForeignKey("asr_speaker.id", ondelete="SET NULL"), nullable=True)
    source_speaker_id = Column(String(200), nullable=True)
    start_ms = Column(Integer, nullable=False)
    end_ms = Column(Integer, nullable=False)
    text = Column(Text, nullable=True)
    channel = Column(String(100), nullable=True)
    confidence = Column(Float, nullable=True)
    raw_payload = Column(JSON, nullable=False, default=dict)


class AsrFusionVersion(Base):
    """单模型转写与指定说话人结果的不可变关联版本。"""

    __tablename__ = "asr_fusion_version"
    __table_args__ = (
        UniqueConstraint("model_run_id", "diarization_result_id", "version", name="uq_asr_fusion_version"),
        Index("ix_asr_fusion_run", "model_run_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    model_run_id = Column(Integer, ForeignKey("asr_model_run.id", ondelete="CASCADE"), nullable=False)
    audio_version_id = Column(Integer, ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False)
    diarization_result_id = Column(Integer, ForeignKey("asr_diarization_result.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    status = Column(String(30), nullable=False, default="UNALIGNED", server_default=text("'UNALIGNED'"))
    algorithm_version = Column(String(40), nullable=False, default="time-overlap-v1", server_default=text("'time-overlap-v1'"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrSpeakerAssignment(Base):
    """按真实时间交集连接转写字符范围与说话人区间，表达未知、混合及重叠状态。"""

    __tablename__ = "asr_speaker_assignment"
    __table_args__ = (
        UniqueConstraint("fusion_version_id", "segment_id", "start_offset", "end_offset", "speaker_turn_id", name="uq_asr_speaker_assignment_span"),
        Index("ix_asr_speaker_assignment_segment", "fusion_version_id", "segment_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    fusion_version_id = Column(Integer, ForeignKey("asr_fusion_version.id", ondelete="CASCADE"), nullable=False, index=True)
    segment_id = Column(Integer, ForeignKey("asr_transcript_segment.id", ondelete="CASCADE"), nullable=True)
    speaker_turn_id = Column(Integer, ForeignKey("asr_speaker_turn.id", ondelete="CASCADE"), nullable=True)
    speaker_id = Column(Integer, ForeignKey("asr_speaker.id", ondelete="SET NULL"), nullable=True)
    start_offset = Column(Integer, nullable=True)
    end_offset = Column(Integer, nullable=True)
    coverage_ratio = Column(Float, nullable=True)
    assignment_status = Column(String(30), nullable=False)
    source = Column(String(30), nullable=False, default="TIME_OVERLAP", server_default=text("'TIME_OVERLAP'"))
    review_status = Column(String(20), nullable=False, default="UNREVIEWED", server_default=text("'UNREVIEWED'"))
    review_version = Column(Integer, nullable=False, default=0, server_default=text("0"))
    confirmed_speaker_id = Column(Integer, ForeignKey("asr_speaker.id", ondelete="SET NULL"), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AsrSpeakerReviewAudit(Base):
    """保留说话人归属人工确认与历史，不覆盖识别段或模型原始结果。"""

    __tablename__ = "asr_speaker_review_audit"
    __table_args__ = (UniqueConstraint("assignment_id", "version", name="uq_asr_speaker_review_version"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    assignment_id = Column(Integer, ForeignKey("asr_speaker_assignment.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    reviewer_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    speaker_id = Column(Integer, ForeignKey("asr_speaker.id", ondelete="SET NULL"), nullable=True)
    review_status = Column(String(20), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrSpeakerNameAudit(Base):
    """审计单个录音内的说话人显示名修改。"""

    __tablename__ = "asr_speaker_name_audit"

    id = Column(Integer, primary_key=True, autoincrement=True)
    speaker_id = Column(Integer, ForeignKey("asr_speaker.id", ondelete="CASCADE"), nullable=False, index=True)
    reviewer_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    revision = Column(Integer, nullable=False)
    previous_name = Column(String(120), nullable=False)
    next_name = Column(String(120), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrMediaAnalysis(Base):
    """固定音频版本的原文件信息、服务端分析摘要和真实多级峰值。"""

    __tablename__ = "asr_media_analysis"
    __table_args__ = (
        UniqueConstraint("processing_run_id", name="uq_asr_media_analysis_run"),
        Index("ix_asr_media_analysis_audio", "audio_version_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_version_id = Column(Integer, ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False)
    processing_run_id = Column(Integer, ForeignKey("asr_processing_run.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(30), nullable=False)
    source = Column(String(50), nullable=True)
    analyzer_version = Column(String(120), nullable=True)
    source_info = Column(JSON, nullable=False, default=dict)
    original_format = Column(JSON, nullable=False, default=dict)
    analysis_pcm = Column(JSON, nullable=False, default=dict)
    signal_statistics = Column(JSON, nullable=False, default=dict)
    peaks = Column(JSON, nullable=False, default=dict)
    processed_range = Column(JSON, nullable=False, default=dict)
    warnings = Column(JSON, nullable=False, default=list)
    analyzed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
