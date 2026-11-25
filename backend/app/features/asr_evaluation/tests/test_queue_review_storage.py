from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database.base import Base
from app.features.asr_evaluation.models import (
    AsrComparison, AsrDiffBlock, AsrModelRun, AsrProcessingWorkItem, AsrReviewAudit, AsrSpeakerNameAudit,
    AsrSpeakerReviewAudit, AsrWorkItem,
)
from app.features.asr_evaluation.runtime import worker as worker_module
from app.features.asr_evaluation.services.comparison_service import list_review_history
from app.features.asr_evaluation.tests.test_regressions import sandbox
from app.platform.model_configuration.models import ModelLegacyBinding, ModelResource, ModelRevision


@pytest.fixture
def storage():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        for name in ("user", "asr_model_run", "asr_processing_run", "asr_diff_block",
                     "asr_speaker_assignment", "asr_speaker"):
            conn.exec_driver_sql(f'CREATE TABLE "{name}" (id INTEGER PRIMARY KEY)')
            conn.exec_driver_sql(f'INSERT INTO "{name}" (id) VALUES (1), (2), (3)')
        for name in ("asr_queue_item", "asr_review_event"):
            assert name in Base.metadata.tables, f"{name} must back ASR writes"
            Base.metadata.tables[name].create(conn)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_new_queues_keep_independent_id_high_waters_and_parent_fks(storage):
    db = storage
    first, processing = AsrWorkItem(run_id=1), AsrProcessingWorkItem(processing_run_id=1)
    db.add_all([first, processing])
    db.commit()
    assert (first.public_id, processing.public_id) == (1, 1)
    db.execute(text("DELETE FROM asr_model_run WHERE id=1"))
    db.add(AsrWorkItem(run_id=2))
    db.commit()
    assert db.query(AsrWorkItem).one().public_id == 2
    assert db.query(AsrProcessingWorkItem).one().public_id == 1
    db.add(AsrProcessingWorkItem(processing_run_id=2, run_id=2))
    with pytest.raises(IntegrityError):
        db.commit()


def test_audit_subjects_survive_selected_speaker_deletion_and_keep_cascades(storage):
    db = storage
    db.add_all([
        AsrReviewAudit(block_id=1, reviewer_id=1, version=2, review_status="CONFIRMED",
                       confirmed_text="", include_reference_sample=True),
        AsrSpeakerReviewAudit(assignment_id=1, reviewer_id=1, version=2,
                              speaker_id=1, review_status="CONFIRMED"),
        AsrSpeakerNameAudit(speaker_id=1, reviewer_id=1, revision=2,
                            previous_name="", next_name="Ada"),
    ])
    db.commit()
    assert db.execute(text("SELECT public_id FROM asr_review_event ORDER BY id")).scalars().all() == [1, 1, 1]
    db.add(AsrSpeakerReviewAudit(assignment_id=1, version=2, review_status="UNKNOWN"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.execute(text('DELETE FROM "user" WHERE id=1'))
    db.execute(text("DELETE FROM asr_speaker WHERE id=1"))
    db.commit()
    assignment = db.query(AsrSpeakerReviewAudit).one()
    assert (assignment.assignment_id, assignment.speaker_id, assignment.reviewer_id) == (1, None, None)
    assert not db.query(AsrSpeakerNameAudit).count()
    block = db.query(AsrReviewAudit).one()
    assert (block.confirmed_text, block.include_reference_sample, block.reviewer_id) == ("", True, None)
    db.execute(text("DELETE FROM asr_speaker_assignment WHERE id=1"))
    db.execute(text("DELETE FROM asr_diff_block WHERE id=1"))
    assert db.execute(text("SELECT count(*) FROM asr_review_event")).scalar_one() == 0


def test_stale_or_mismatched_claim_cannot_modify_any_model_run(sandbox, monkeypatch):
    db, factory, *_ = sandbox
    monkeypatch.setattr(worker_module, "SessionLocal", factory)
    worker = worker_module.AsrWorker()
    item_id, run_id, owner, generation, _ = worker._claim_next()
    other = db.query(AsrModelRun).filter(AsrModelRun.id != run_id).first()
    worker._finish(other.id, item_id, owner, generation, "FAILED", "wrong parent")
    db.expire_all()
    assert other.status == "PENDING"
    item = db.get(AsrWorkItem, item_id)
    item.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    worker._reschedule(item_id, run_id, owner, generation, delay_seconds=2, reset_submit=True)
    db.expire_all()
    assert db.get(AsrModelRun, run_id).status == "SUBMITTING"
    assert db.get(AsrWorkItem, item_id).lease_owner == owner


def test_recovery_polls_a_saved_receipt_from_an_interrupted_submission(sandbox, monkeypatch):
    db, factory, *_ = sandbox
    monkeypatch.setattr(worker_module, "SessionLocal", factory)
    worker = worker_module.AsrWorker()
    item_id, run_id, owner, generation, _ = worker._claim_next()
    db.get(AsrModelRun, run_id).remote_task_id = "saved-receipt"
    db.get(AsrWorkItem, item_id).lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    recovered = worker._claim_next()
    assert recovered is not None
    assert recovered[:2] == (item_id, run_id)
    assert recovered[2] != owner and recovered[3:] == (generation + 1, False)


@pytest.mark.parametrize("lose_lease", [False, True])
def test_worker_rechecks_lease_and_saved_receipt_when_http_slot_opens(sandbox, monkeypatch, lose_lease):
    db, factory, *_ = sandbox
    monkeypatch.setattr(worker_module, "SessionLocal", factory)
    worker = worker_module.AsrWorker()
    claim = worker._claim_next()
    item_id, run_id, *_ = claim

    @contextmanager
    def delayed_slot(bind):
        with factory() as session:
            session.get(AsrModelRun, run_id).remote_task_id = "accepted"
            if lose_lease:
                item = session.get(AsrWorkItem, item_id)
                item.lease_owner = "replacement"
                item.lease_generation += 1
            session.commit()
        yield

    monkeypatch.setattr(worker_module, "asr_request_slot", delayed_slot)
    monkeypatch.setattr(worker._provider, "submit", lambda *_a, **_kw: pytest.fail("duplicated a known submission"))
    def poll(_db, *, project_id, execution, remote_task_id):
        assert not lose_lease and remote_task_id == "accepted"
        return {"state": "SUCCEEDED", "transcript": "polled"}
    monkeypatch.setattr(worker._provider, "poll", poll)
    worker._execute_claim(*claim)
    db.expire_all()
    run = db.get(AsrModelRun, run_id)
    assert (run.status, run.transcript) == (("SUBMITTING", None) if lose_lease else ("SUCCEEDED", "polled"))


def test_equal_version_text_history_uses_legacy_id_order(sandbox):
    db, _, actor, audio, _, _, job = sandbox
    comparison = AsrComparison(project_id=audio.project_id, job_id=job["id"], audio_id=audio.id)
    db.add(comparison)
    db.flush()
    block = AsrDiffBlock(comparison_id=comparison.id, ordinal=1)
    db.add(block)
    db.flush()
    for public_id, value in ((9, "second"), (3, "first")):
        db.add(AsrReviewAudit(public_id=public_id, block_id=block.id, version=1,
                              review_status="CONFIRMED", confirmed_text=value))
    db.commit()
    # A different access path must not let internal insertion order leak to the API.
    db.execute(text("DROP INDEX ix_asr_review_block_version"))
    db.execute(text("CREATE INDEX test_asr_review_block_version ON asr_review_event(block_id, version, id)"))
    history = list_review_history(db, comparison.id, block.id, actor)
    assert [entry["confirmed_text"] for entry in history] == ["first", "second"]


@pytest.mark.parametrize("allow,scope,revision_enabled,expected", [
    (True, "same", True, "SUCCEEDED"),
    (False, "same", True, "FAILED"),
    (True, "other", True, "FAILED"),
    (True, "same", False, "FAILED"),
])
def test_worker_preserves_project_local_connection_admission(sandbox, monkeypatch, allow, scope, revision_enabled, expected):
    db, factory, _, audio, connections, *_ = sandbox
    connection = connections[0]
    resource = ModelResource(resource_key="legacy-asr", category="ASR", visibility="PROJECT",
                             project_id=audio.project_id, display_name="local", status="ACTIVE")
    db.add(resource)
    db.flush()
    revision = ModelRevision(resource_id=resource.id, version=1, provider="fake", adapter_key="generic-json-http",
                             model_name="test", enabled=revision_enabled, legacy_connection_id=connection.id)
    db.add(revision)
    db.flush()
    binding = ModelLegacyBinding(legacy_kind="ASR_CONNECTION", legacy_id=connection.id, resource_id=resource.id,
                                 revision_id=revision.id, allow_project_execution=allow,
                                 project_id=audio.project_id if scope == "same" else audio.project_id + 1)
    db.add(binding)
    db.commit()
    monkeypatch.setattr(worker_module, "SessionLocal", factory)
    worker = worker_module.AsrWorker()
    if expected == "SUCCEEDED":
        monkeypatch.setattr(worker._provider, "submit", lambda *_a, **_kw: {"state": "SUCCEEDED", "transcript": "ok"})
    else:
        monkeypatch.setattr(worker._provider, "submit", lambda *_a, **_kw: pytest.fail("ineligible project alias submitted"))
    claim = worker._claim_next()
    assert db.get(AsrModelRun, claim[1]).connection_id == connection.id
    worker._execute_claim(*claim)
    db.expire_all()
    assert db.get(AsrModelRun, claim[1]).status == expected
