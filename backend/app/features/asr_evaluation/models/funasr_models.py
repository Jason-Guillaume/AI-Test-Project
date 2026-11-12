"""Persistent FunASR ground truth, API binding, and multi-round tuning state."""

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class AsrApiBinding(Base):
    __tablename__ = "asr_api_binding"
    __table_args__ = (Index("ix_asr_api_binding_project", "project_id", "is_active"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    api_interface_id = Column(Integer, ForeignKey("api_interface.id", ondelete="SET NULL"), nullable=True, index=True)
    interface_version = Column(Integer, nullable=False)
    source_hash = Column(String(64), nullable=True)
    environment_name = Column(String(100), nullable=False)
    config_snapshot = Column(JSON, nullable=False)
    execution_ciphertext = Column(Text, nullable=False)
    response_mapping = Column(JSON, nullable=False, default=dict)
    timeout_seconds = Column(Integer, nullable=False, default=180, server_default=text("180"))
    max_response_bytes = Column(Integer, nullable=False, default=8_000_000, server_default=text("8000000"))
    is_active = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class AsrGroundTruthVersion(Base):
    __tablename__ = "asr_ground_truth_version"
    __table_args__ = (
        UniqueConstraint("audio_version_id", "version", name="uq_asr_ground_truth_version"),
        Index("ix_asr_ground_truth_audio_current", "audio_id", "is_current"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_id = Column(Integer, ForeignKey("asr_audio.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_version_id = Column(Integer, ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    raw_sha256 = Column(String(64), nullable=False)
    raw_document = Column(JSON, nullable=False)
    mapping_snapshot = Column(JSON, nullable=False)
    normalized_json = Column(JSON, nullable=False)
    markdown = Column(Text, nullable=False)
    is_current = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AsrTuningSession(Base):
    __tablename__ = "asr_tuning_session"
    __table_args__ = (
        Index("ix_asr_tuning_session_queue", "status", "next_run_at"),
        Index("ix_asr_tuning_session_project", "project_id", "created_at"),
        UniqueConstraint("idempotency_key", name="uq_asr_tuning_session_idempotency"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    binding_id = Column(Integer, ForeignKey("asr_api_binding.id", ondelete="RESTRICT"), nullable=False)
    model_config_id = Column(Integer, ForeignKey("model_configuration.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String(40), nullable=False, default="QUEUED", server_default=text("'QUEUED'"), index=True)
    mode = Column(String(30), nullable=False, default="AUTO_TUNE", server_default=text("'AUTO_TUNE'"))
    config_snapshot = Column(JSON, nullable=False)
    execution_ciphertext = Column(Text, nullable=False)
    idempotency_key = Column(String(128), nullable=False)
    current_round = Column(Integer, nullable=False, default=1, server_default=text("1"))
    best_round_id = Column(Integer, nullable=True)
    max_rounds = Column(Integer, nullable=False)
    max_asr_requests = Column(Integer, nullable=False)
    asr_requests_used = Column(Integer, nullable=False, default=0, server_default=text("0"))
    max_ai_calls = Column(Integer, nullable=False)
    ai_calls_used = Column(Integer, nullable=False, default=0, server_default=text("0"))
    no_improvement_limit = Column(Integer, nullable=False)
    no_improvement_rounds = Column(Integer, nullable=False, default=0, server_default=text("0"))
    failed_items_limit = Column(Integer, nullable=False)
    target_micro_cer = Column(Float, nullable=True)
    min_improvement = Column(Float, nullable=False)
    max_sample_degradation = Column(Float, nullable=False)
    night_start = Column(String(5), nullable=False, default="22:00", server_default=text("'22:00'"))
    night_end = Column(String(5), nullable=False, default="07:00", server_default=text("'07:00'"))
    window_enabled = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    stop_reason = Column(Text, nullable=True)
    lease_owner = Column(String(160), nullable=True)
    lease_generation = Column(Integer, nullable=False, default=0, server_default=text("0"))
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    cancel_requested = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AsrTuningRound(Base):
    __tablename__ = "asr_tuning_round"
    __table_args__ = (
        UniqueConstraint("session_id", "ordinal", name="uq_asr_tuning_round_ordinal"),
        Index("ix_asr_tuning_round_status", "session_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("asr_tuning_session.id", ondelete="CASCADE"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)
    status = Column(String(40), nullable=False, default="QUEUED", server_default=text("'QUEUED'"))
    parameters = Column(JSON, nullable=False)
    parameter_hash = Column(String(64), nullable=False)
    metrics = Column(JSON, nullable=False, default=dict)
    report_json = Column(JSON, nullable=True)
    report_markdown = Column(Text, nullable=True)
    candidate_json = Column(JSON, nullable=True)
    analysis_stage = Column(String(30), nullable=True)
    accepted = Column(Boolean, nullable=True)
    stop_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)


class AsrTuningItem(Base):
    __tablename__ = "asr_tuning_item"
    __table_args__ = (
        UniqueConstraint("round_id", "audio_id", name="uq_asr_tuning_item_round_audio"),
        UniqueConstraint("idempotency_key", name="uq_asr_tuning_item_idempotency"),
        Index("ix_asr_tuning_item_round_status", "round_id", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey("asr_tuning_session.id", ondelete="CASCADE"), nullable=False, index=True)
    round_id = Column(Integer, ForeignKey("asr_tuning_round.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    audio_id = Column(Integer, ForeignKey("asr_audio.id", ondelete="RESTRICT"), nullable=False)
    audio_version_id = Column(Integer, ForeignKey("asr_audio_version.id", ondelete="RESTRICT"), nullable=False)
    ground_truth_version_id = Column(Integer, ForeignKey("asr_ground_truth_version.id", ondelete="RESTRICT"), nullable=False)
    ordinal = Column(Integer, nullable=False)
    status = Column(String(40), nullable=False, default="PENDING", server_default=text("'PENDING'"), index=True)
    idempotency_key = Column(String(80), nullable=False)
    response_received = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    response_json = Column(JSON, nullable=True)
    normalized_json = Column(JSON, nullable=True)
    ground_truth_json = Column(JSON, nullable=True)
    answer_markdown = Column(Text, nullable=True)
    response_markdown = Column(Text, nullable=True)
    metrics = Column(JSON, nullable=True)
    review_json = Column(JSON, nullable=True)
    review_status = Column(String(40), nullable=False, default="PENDING", server_default=text("'PENDING'"))
    duration_ms = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    submit_intent_at = Column(DateTime(timezone=True), nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
