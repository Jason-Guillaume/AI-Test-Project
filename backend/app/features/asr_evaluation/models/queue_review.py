"""Typed ASR queue entries and human review history."""

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, FetchedValue, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, event, func, text,
)
from sqlalchemy.orm import synonym

from app.core.database.base import Base


class AsrQueueItem(Base):
    __tablename__ = "asr_queue_item"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'MODEL_RUN' AND run_id IS NOT NULL AND processing_run_id IS NULL) OR "
            "(kind = 'PROCESSING_RUN' AND processing_run_id IS NOT NULL AND run_id IS NULL)",
            name="ck_asr_queue_parent",
        ),
        UniqueConstraint("kind", "public_id", name="uq_asr_queue_public"),
        UniqueConstraint("run_id", name="uq_asr_queue_model_run"),
        UniqueConstraint("processing_run_id", name="uq_asr_queue_processing_run"),
        Index("ix_asr_queue_available", "kind", "available_at", "public_id"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True)
    kind = Column(String(24), nullable=False)
    public_id = Column(Integer, nullable=False, server_default=FetchedValue())
    run_id = Column(Integer, ForeignKey("asr_model_run.id", ondelete="CASCADE"))
    processing_run_id = Column(Integer, ForeignKey("asr_processing_run.id", ondelete="CASCADE"))
    available_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    lease_owner = Column(String(160))
    lease_generation = Column(Integer, nullable=False, default=0, server_default=text("0"))
    lease_expires_at = Column(DateTime(timezone=True))
    attempts = Column(Integer, nullable=False, default=0, server_default=text("0"))
    __mapper_args__ = {"polymorphic_on": kind}


class AsrWorkItem(AsrQueueItem):
    __mapper_args__ = {"polymorphic_identity": "MODEL_RUN"}


class AsrProcessingWorkItem(AsrQueueItem):
    __mapper_args__ = {"polymorphic_identity": "PROCESSING_RUN"}


class AsrReviewEvent(Base):
    __tablename__ = "asr_review_event"
    __table_args__ = (
        CheckConstraint(
            "(kind = 'TEXT' AND block_id IS NOT NULL AND assignment_id IS NULL "
            "AND subject_speaker_id IS NULL AND selected_speaker_id IS NULL "
            "AND review_status IS NOT NULL AND previous_name IS NULL AND next_name IS NULL) OR "
            "(kind = 'SPEAKER_ASSIGNMENT' AND assignment_id IS NOT NULL AND block_id IS NULL "
            "AND subject_speaker_id IS NULL AND review_status IS NOT NULL AND confirmed_text IS NULL "
            "AND NOT include_reference_sample AND previous_name IS NULL AND next_name IS NULL) OR "
            "(kind = 'SPEAKER_NAME' AND subject_speaker_id IS NOT NULL AND block_id IS NULL "
            "AND assignment_id IS NULL AND selected_speaker_id IS NULL AND review_status IS NULL "
            "AND confirmed_text IS NULL AND NOT include_reference_sample "
            "AND previous_name IS NOT NULL AND next_name IS NOT NULL)",
            name="ck_asr_review_subject",
        ),
        UniqueConstraint("kind", "public_id", name="uq_asr_review_public"),
        UniqueConstraint("assignment_id", "version", name="uq_asr_review_assignment_version"),
        Index("ix_asr_review_block_version", "block_id", "version", "public_id"),
        Index("ix_asr_review_subject_speaker", "subject_speaker_id"),
        {"sqlite_autoincrement": True},
    )

    id = Column(Integer, primary_key=True)
    kind = Column(String(24), nullable=False)
    public_id = Column(Integer, nullable=False, server_default=FetchedValue())
    block_id = Column(Integer, ForeignKey("asr_diff_block.id", ondelete="CASCADE"))
    assignment_id = Column(Integer, ForeignKey("asr_speaker_assignment.id", ondelete="CASCADE"))
    subject_speaker_id = Column(Integer, ForeignKey("asr_speaker.id", ondelete="CASCADE"))
    selected_speaker_id = Column(Integer, ForeignKey("asr_speaker.id", ondelete="SET NULL"))
    reviewer_id = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"))
    version = Column(Integer, nullable=False)
    review_status = Column(String(20))
    confirmed_text = Column(Text)
    include_reference_sample = Column(Boolean, nullable=False, default=False, server_default=text("false"))
    previous_name = Column(String(120))
    next_name = Column(String(120))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    __mapper_args__ = {"polymorphic_on": kind}


class AsrReviewAudit(AsrReviewEvent):
    __mapper_args__ = {"polymorphic_identity": "TEXT"}


class AsrSpeakerReviewAudit(AsrReviewEvent):
    __mapper_args__ = {"polymorphic_identity": "SPEAKER_ASSIGNMENT"}
    speaker_id = synonym("selected_speaker_id")


class AsrSpeakerNameAudit(AsrReviewEvent):
    __mapper_args__ = {"polymorphic_identity": "SPEAKER_NAME"}
    speaker_id = synonym("subject_speaker_id")
    revision = synonym("version")


@event.listens_for(AsrQueueItem, "before_insert", propagate=True)
@event.listens_for(AsrReviewEvent, "before_insert", propagate=True)
def _sqlite_public_id(mapper, connection, row):
    """SQLite's built-in sequence storage stands in for PostgreSQL's per-kind sequences."""
    if connection.dialect.name != "sqlite" or row.public_id is not None:
        return
    sequence = f"{row.__tablename__}_{row.kind}"
    connection.execute(text(
        "INSERT INTO sqlite_sequence(name, seq) SELECT :name, 0 "
        "WHERE NOT EXISTS (SELECT 1 FROM sqlite_sequence WHERE name = :name)"
    ), {"name": sequence})
    row.public_id = connection.execute(text(
        "UPDATE sqlite_sequence SET seq = seq + 1 WHERE name = :name RETURNING seq"
    ), {"name": sequence}).scalar_one()
