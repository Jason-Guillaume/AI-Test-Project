"""Persistent idempotent queue for model-backed ASR parameter suggestions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder

from app.core.database.session import SessionLocal
from app.core.http.errors import bad_request, conflict, not_found
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import User
from app.features.asr_evaluation.models import (
    AsrComparison, AsrDiffBlock, AsrModelRun, AsrParameterSet, AsrSuggestionJob,
)
from app.features.asr_evaluation.services.comparison_service import _model_access, create_suggestions
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project


def _input_snapshot(db: Session, comparison: AsrComparison, model_config_id: int) -> dict:
    """Freeze the exact reviewed evidence and ASR parameter version used for one suggestion job."""
    test_run = db.query(AsrModelRun).filter(
        AsrModelRun.job_id == comparison.job_id,
        AsrModelRun.audio_id == comparison.audio_id,
        AsrModelRun.role == "TEST",
    ).first()
    parameter_set = db.get(AsrParameterSet, test_run.parameter_set_id) if test_run and test_run.parameter_set_id else None
    model = db.get(ModelConfiguration, model_config_id)
    if parameter_set is None or model is None:
        raise bad_request("建议任务缺少待测参数版本或文本模型")
    blocks = db.query(AsrDiffBlock).filter(
        AsrDiffBlock.comparison_id == comparison.id,
        AsrDiffBlock.review_status == "CONFIRMED",
    ).order_by(AsrDiffBlock.ordinal).limit(100).all()
    return {
        "comparison": {"id": comparison.id, "version": comparison.version},
        "model": {"id": model.id, "updated_at": model.updated_at.isoformat() if model.updated_at else None},
        "parameter_set": {
            "id": parameter_set.id, "version": parameter_set.version,
            "parameters": parameter_set.parameters or {}, "definitions": parameter_set.definitions or [],
        },
        "confirmed_blocks": [{
            "id": row.id, "ordinal": row.ordinal, "test_text": row.test_text,
            "reference_a_text": row.reference_a_text, "reference_b_text": row.reference_b_text,
            "confirmed_text": row.confirmed_text, "review_version": row.review_version,
        } for row in blocks],
    }


def _digest(snapshot: dict) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dump_job(row: AsrSuggestionJob) -> dict:
    return {
        "id": row.id, "project_id": row.project_id, "comparison_id": row.comparison_id,
        "model_config_id": row.model_config_id, "status": row.status, "attempts": row.attempts,
        "result": row.result_json or {}, "error_message": row.error_message,
        "created_at": row.created_at, "started_at": row.started_at, "finished_at": row.finished_at,
    }


def create_suggestion_job(db: Session, comparison_id: int, model_config_id: int, actor: User) -> dict:
    """Create or return a deduplicated job for the same comparison, evidence, model and parameters."""
    comparison = db.get(AsrComparison, comparison_id)
    if comparison is None:
        raise not_found("识别结果对比不存在")
    require_writable_project(db, comparison.project_id, actor)
    _model_access(db, comparison.project_id, actor, model_config_id)
    snapshot = _input_snapshot(db, comparison, model_config_id)
    key = _digest(snapshot)
    existing = db.query(AsrSuggestionJob).filter_by(idempotency_key=key).one_or_none()
    if existing is not None:
        return _dump_job(existing)
    row = AsrSuggestionJob(
        project_id=comparison.project_id, comparison_id=comparison.id,
        model_config_id=model_config_id, idempotency_key=key, input_snapshot=snapshot,
        status="QUEUED", requested_by=actor.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _dump_job(row)


def list_suggestion_jobs(db: Session, comparison_id: int, actor: User) -> dict:
    comparison = db.get(AsrComparison, comparison_id)
    if comparison is None:
        raise not_found("识别结果对比不存在")
    get_project_or_404(db, comparison.project_id, actor)
    rows = db.query(AsrSuggestionJob).filter(
        AsrSuggestionJob.comparison_id == comparison_id,
    ).order_by(AsrSuggestionJob.id.desc()).limit(100).all()
    return {"items": [_dump_job(row) for row in rows]}


def retry_suggestion_job(db: Session, job_id: int, actor: User) -> dict:
    """Explicitly retry a known failure only while its evidence/model snapshot is still current."""
    row = db.query(AsrSuggestionJob).filter(AsrSuggestionJob.id == job_id).with_for_update().first()
    if row is None:
        raise not_found("建议任务不存在")
    require_writable_project(db, row.project_id, actor)
    if row.status != "FAILED":
        raise conflict("只有明确失败的建议任务可以重试；状态不确定的请求不会自动重复调用")
    comparison = db.get(AsrComparison, row.comparison_id)
    if comparison is None:
        raise not_found("识别结果对比不存在")
    current = _input_snapshot(db, comparison, row.model_config_id)
    _model_access(db, comparison.project_id, actor, row.model_config_id)
    if _digest(current) != row.idempotency_key:
        raise conflict("已确认片段、模型或参数版本已变化；请创建新的建议任务")
    row.status = "QUEUED"
    row.error_message = None
    row.result_json = {}
    row.started_at = None
    row.finished_at = None
    row.lease_owner = None
    row.lease_expires_at = None
    db.commit()
    db.refresh(row)
    return _dump_job(row)


def recover_expired_suggestion_jobs(db: Session, *, now: datetime | None = None) -> int:
    """Do not replay a model call with an expired worker lease because remote billing is uncertain."""
    now = now or datetime.now(timezone.utc)
    rows = db.query(AsrSuggestionJob).filter(
        AsrSuggestionJob.status == "RUNNING",
        AsrSuggestionJob.lease_expires_at.is_not(None),
        AsrSuggestionJob.lease_expires_at < now,
    ).with_for_update(skip_locked=True).all()
    for row in rows:
        row.status = "RECONCILIATION_REQUIRED"
        row.error_message = "Worker 租约过期；外部模型是否已处理此请求无法确认，平台未自动重试。"
        row.finished_at = now
        row.lease_owner = None
        row.lease_expires_at = None
    if rows:
        db.commit()
    return len(rows)


def extend_suggestion_lease(job_id: int, owner: str, generation: int, *, lease_seconds: int = 120) -> bool:
    db = SessionLocal()
    try:
        row = db.get(AsrSuggestionJob, job_id)
        if row is None or row.status != "RUNNING" or row.lease_owner != owner or row.lease_generation != generation:
            return False
        row.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=lease_seconds)
        db.commit()
        return True
    except Exception:
        db.rollback()
        return False
    finally:
        db.close()


def execute_suggestion_job(
    job_id: int, owner: str, generation: int, *, session_factory: Callable[[], Session] = SessionLocal,
) -> None:
    """Run a frozen suggestion input and persist its output only for the active lease generation."""
    db = session_factory()
    try:
        row = db.get(AsrSuggestionJob, job_id)
        if row is None or row.status != "RUNNING" or row.lease_owner != owner or row.lease_generation != generation:
            return
        actor = db.get(User, row.requested_by) if row.requested_by else None
        if actor is None or not actor.is_active:
            raise bad_request("请求用户已停用或不存在；请由有权限的项目成员重新创建建议任务")
        result = create_suggestions(
            db, row.comparison_id, actor, model_config_id=row.model_config_id,
            input_snapshot=row.input_snapshot, commit=False,
        )
        row = db.get(AsrSuggestionJob, job_id)
        if row is None or row.lease_owner != owner or row.lease_generation != generation:
            return
        row.status = "SUCCEEDED"
        # Persist the same wire-safe timestamps that FastAPI would emit. JSON columns
        # cannot encode the datetime objects returned by the suggestion DTO directly.
        row.result_json = jsonable_encoder(result)
        row.error_message = None
        row.finished_at = datetime.now(timezone.utc)
        row.lease_owner = None
        row.lease_expires_at = None
        db.commit()
    except Exception as exc:
        db.rollback()
        row = db.get(AsrSuggestionJob, job_id)
        if row is not None and row.lease_owner == owner and row.lease_generation == generation:
            row.status = "FAILED"
            row.error_message = str(exc)[:2000]
            row.finished_at = datetime.now(timezone.utc)
            row.lease_owner = None
            row.lease_expires_at = None
            db.commit()
    finally:
        db.close()


__all__ = [
    "create_suggestion_job", "execute_suggestion_job", "extend_suggestion_lease",
    "list_suggestion_jobs", "recover_expired_suggestion_jobs", "retry_suggestion_job",
]
