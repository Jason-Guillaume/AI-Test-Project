"""Candidate reruns stay pinned to synthetic source slots and commit atomically."""

from __future__ import annotations

import pytest

from app.core.security.crypto import encrypt_secret
from app.features.asr_evaluation.models import (
    AsrAudio, AsrComparison, AsrExperiment, AsrJob, AsrModelRun, AsrWorkItem,
)
from app.features.asr_evaluation.schemas import ExperimentCreate, JobCreate
from app.features.asr_evaluation.services import comparison_service
from app.features.asr_evaluation.services.comparison_service import create_experiment, record_run_result, run_experiment
from app.features.asr_evaluation.services.job_service import create_job
from app.platform.model_configuration.models import ModelParameterProfile, ModelTaskSlot
from app.platform.model_configuration.services.model_center_service import create_resource
from app.platform.model_configuration.tests.test_model_center import _asr_resource, center_sandbox
from app.features.asr_evaluation.tests.test_regressions import sandbox


def _comparison_for_center(center_sandbox, reuse_reference_results: bool = False):
    db, admin, _owner_a, _owner_b, project, _other_project = center_sandbox
    audio = AsrAudio(
        project_id=project.id, name="synthetic-rerun-audio",
        url_ciphertext=encrypt_secret("https://audio.example.invalid/a.wav"), url_display="https://audio.example.invalid/a.wav",
        created_by=admin.id,
    )
    db.add(audio)
    db.commit()
    slots = []
    original_profile_ids = {}
    for index, slot in enumerate(("TEST", "REFERENCE_A", "REFERENCE_B")):
        body = _asr_resource([project.id]).model_copy(update={"display_name": f"synthetic-model-{index}"})
        created = create_resource(db, body, admin)
        revision = created["current_revision"]
        profile_id = revision["profiles"][0]["id"]
        slots.append({"slot": slot, "resource_id": created["id"], "revision_id": revision["id"], "profile_id": profile_id})
        original_profile_ids[slot] = profile_id
    source_job = create_job(db, JobCreate(project_id=project.id, audio_ids=[audio.id], model_slots=slots), admin)
    for run in db.query(AsrModelRun).filter_by(job_id=source_job["id"]).all():
        record_run_result(db, run.id, status="SUCCEEDED", transcript="合成参考文本。", segments=[])
    comparison = db.query(AsrComparison).filter_by(job_id=source_job["id"]).one()
    experiment = create_experiment(db, ExperimentCreate(
        comparison_id=comparison.id, candidate_parameters={"language": "en"},
        change_summary="isolated rerun regression", reuse_reference_results=reuse_reference_results,
    ), admin)
    return db, admin, project, source_job, comparison, experiment, original_profile_ids


@pytest.mark.parametrize("reuse_reference_results", [False, True])
def test_model_center_candidate_rerun_preserves_source_slots(center_sandbox, reuse_reference_results):
    db, admin, project, source_job, comparison, experiment, original_profiles = _comparison_for_center(
        center_sandbox, reuse_reference_results,
    )
    outcome = run_experiment(db, experiment["id"], admin)
    candidate_slots = {
        row.slot: row for row in db.query(ModelTaskSlot).filter_by(
            task_kind="ASR_JOB", task_id=outcome["job"]["id"],
        ).all()
    }
    source_slots = {
        row.slot: row for row in db.query(ModelTaskSlot).filter_by(
            task_kind="ASR_JOB", task_id=source_job["id"],
        ).all()
    }
    assert set(candidate_slots) == {"TEST", "REFERENCE_A", "REFERENCE_B"}
    for slot in ("TEST", "REFERENCE_A", "REFERENCE_B"):
        assert candidate_slots[slot].resource_id == source_slots[slot].resource_id
        assert candidate_slots[slot].revision_id == source_slots[slot].revision_id
    candidate_test_profile = db.get(ModelParameterProfile, candidate_slots["TEST"].profile_id)
    assert candidate_test_profile.parameter_values == {"language": "en"}
    assert candidate_slots["TEST"].profile_id != original_profiles["TEST"]
    for slot in ("REFERENCE_A", "REFERENCE_B"):
        assert candidate_slots[slot].profile_id == original_profiles[slot]

    runs = db.query(AsrModelRun).filter_by(job_id=outcome["job"]["id"], audio_id=comparison.audio_id).all()
    test_run = next(row for row in runs if row.role == "TEST")
    reference_runs = [row for row in runs if row.role == "REFERENCE"]
    assert test_run.status == "PENDING"
    if reuse_reference_results:
        assert len(reference_runs) == 2
        assert all(row.status == "SUCCEEDED" and row.transcript == "合成参考文本。" for row in reference_runs)
        assert outcome["job"]["config_snapshot"]["reference_reuse"]["source_comparison_id"] == comparison.id
    else:
        assert all(row.status == "PENDING" for row in reference_runs)


def test_failed_candidate_creation_rolls_back_and_can_be_retried(center_sandbox, monkeypatch):
    db, admin, _project, source_job, _comparison, experiment, _profiles = _comparison_for_center(center_sandbox)
    initial_job_count = db.query(AsrJob).count()
    initial_item_count = db.query(AsrWorkItem).count()
    initial_profile_count = db.query(ModelParameterProfile).count()
    original_create_job = comparison_service.create_job

    def fail_after_queue_flush(*args, **kwargs):
        original_create_job(*args, **kwargs)
        raise RuntimeError("synthetic failure after queue flush")

    monkeypatch.setattr(comparison_service, "create_job", fail_after_queue_flush)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        run_experiment(db, experiment["id"], admin)
    failed = db.get(AsrExperiment, experiment["id"])
    assert failed.status == "FAILED"
    assert failed.candidate_job_id is None
    assert "synthetic failure" in failed.failure_reason
    assert db.query(AsrJob).count() == initial_job_count
    assert db.query(AsrWorkItem).count() == initial_item_count
    assert db.query(ModelParameterProfile).count() == initial_profile_count

    monkeypatch.setattr(comparison_service, "create_job", original_create_job)
    retried = run_experiment(db, experiment["id"], admin)
    assert retried["job"]["id"] is not None
    assert db.get(AsrExperiment, experiment["id"]).status == "RUNNING"


def test_legacy_candidate_rerun_remains_supported(sandbox):
    db, _factory, admin, audio, _connections, parameter_set, source_job = sandbox
    parameter_set.parameters = {"language": "zh"}
    parameter_set.definitions = [{"path": "/language", "display_name": "语言", "value_type": "string"}]
    db.commit()
    for run in db.query(AsrModelRun).filter_by(job_id=source_job["id"]).all():
        record_run_result(db, run.id, status="SUCCEEDED", transcript="legacy synthetic text", segments=[])
    comparison = db.query(AsrComparison).filter_by(job_id=source_job["id"], audio_id=audio.id).one()
    experiment = create_experiment(db, ExperimentCreate(
        comparison_id=comparison.id, candidate_parameters={"language": "en"},
        change_summary="legacy compatibility rerun", reuse_reference_results=False,
    ), admin)
    result = run_experiment(db, experiment["id"], admin)
    assert result["job"]["status"] == "QUEUED"
    assert db.query(ModelTaskSlot).filter_by(task_kind="ASR_JOB", task_id=result["job"]["id"]).count() == 0
    candidate_run = db.query(AsrModelRun).filter_by(job_id=result["job"]["id"], role="TEST").one()
    assert candidate_run.parameter_set_id != db.query(AsrModelRun).filter_by(
        job_id=source_job["id"], role="TEST",
    ).one().parameter_set_id
