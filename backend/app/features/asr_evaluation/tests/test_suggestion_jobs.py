"""Persistent suggestion jobs are idempotent and can be executed with a synthetic provider."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

from app.core.models.configuration import ModelConfiguration
from app.features.asr_evaluation.models import AsrDiffBlock, AsrSuggestion, AsrSuggestionJob
from app.features.asr_evaluation.services.suggestion_job_service import (
    create_suggestion_job, execute_suggestion_job, recover_expired_suggestion_jobs, retry_suggestion_job,
)
from app.platform.model_configuration.tests.test_model_center import center_sandbox
from app.features.asr_evaluation.tests.test_candidate_rerun import _comparison_for_center


def _add_model(db, actor):
    row = ModelConfiguration(
        domain_id=f"synthetic-suggestion-{actor.id}", label="合成建议模型",
        provider="openai-compatible", api_base="https://model.example.invalid/v1",
        model_name="synthetic-text", is_enabled=True, created_by=actor.id,
    )
    db.add(row)
    db.commit()
    return row


def _confirmed_fixture(center_sandbox):
    db, actor, project, _source_job, comparison, _experiment, _profiles = _comparison_for_center(center_sandbox)
    block = db.query(AsrDiffBlock).filter_by(comparison_id=comparison.id).first()
    block.review_status = "CONFIRMED"
    block.confirmed_text = "人工确认的合成片段。"
    block.review_version += 1
    db.commit()
    model = _add_model(db, actor)
    return db, actor, comparison, block, model


def test_suggestion_job_deduplicates_same_review_snapshot(center_sandbox):
    db, actor, comparison, _block, model = _confirmed_fixture(center_sandbox)
    first = create_suggestion_job(db, comparison.id, model.id, actor)
    repeated = create_suggestion_job(db, comparison.id, model.id, actor)
    assert first["id"] == repeated["id"]
    assert first["status"] == "QUEUED"


def test_failed_job_retries_only_when_snapshot_is_unchanged(center_sandbox):
    db, actor, comparison, block, model = _confirmed_fixture(center_sandbox)
    job_data = create_suggestion_job(db, comparison.id, model.id, actor)
    job = db.get(AsrSuggestionJob, job_data["id"])
    job.status = "FAILED"
    job.error_message = "synthetic failure"
    db.commit()
    retried = retry_suggestion_job(db, job.id, actor)
    assert retried["status"] == "QUEUED"

    block.confirmed_text = "新版确认文本。"
    block.review_version += 1
    db.commit()
    job.status = "FAILED"
    db.commit()
    with pytest.raises(HTTPException, match="片段、模型或参数版本已变化"):
        retry_suggestion_job(db, job.id, actor)


def test_suggestion_worker_persists_synthetic_result_without_external_call(center_sandbox, monkeypatch):
    db, actor, comparison, block, model = _confirmed_fixture(center_sandbox)
    job_data = create_suggestion_job(db, comparison.id, model.id, actor)
    job = db.get(AsrSuggestionJob, job_data["id"])
    job.status = "RUNNING"
    job.lease_owner = "synthetic-worker"
    job.lease_generation = 2
    job.lease_expires_at = datetime.now(timezone.utc)
    db.commit()

    class SyntheticProvider:
        def __init__(self, *_args, **_kwargs):
            pass

        def generate_structured(self, *_args, **_kwargs):
            return {"suggestions": [{
                "observation": "已确认片段可用于检查语言参数。",
                "evidence_block_ids": [block.id], "parameter_path": "/language",
                "candidate_value": "en", "rationale": "这是合成回归建议。",
                "validation_steps": "固定音频版本后复跑并回听该片段。",
            }]}

    import app.llm.providers.openai_compatible as provider_module
    monkeypatch.setattr(provider_module, "ProductionLLMProvider", SyntheticProvider)
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    execute_suggestion_job(job.id, "synthetic-worker", 2, session_factory=factory)

    db.expire_all()
    finished = db.get(AsrSuggestionJob, job.id)
    assert finished.status == "SUCCEEDED", finished.error_message
    assert finished.result_json["source"] == "MODEL"
    suggestions = db.query(AsrSuggestion).filter_by(comparison_id=comparison.id).all()
    assert len(suggestions) == 1
    assert suggestions[0].candidate_value == "en"


def test_expired_suggestion_lease_requires_reconciliation_without_replay(center_sandbox):
    db, actor, comparison, _block, model = _confirmed_fixture(center_sandbox)
    job_data = create_suggestion_job(db, comparison.id, model.id, actor)
    job = db.get(AsrSuggestionJob, job_data["id"])
    job.status = "RUNNING"
    job.lease_owner = "stopped-worker"
    job.lease_generation = 3
    job.lease_expires_at = datetime.now(timezone.utc)
    db.commit()

    assert recover_expired_suggestion_jobs(db, now=datetime.now(timezone.utc)) == 1
    db.refresh(job)
    assert job.status == "RECONCILIATION_REQUIRED"
    assert "未自动重试" in job.error_message
