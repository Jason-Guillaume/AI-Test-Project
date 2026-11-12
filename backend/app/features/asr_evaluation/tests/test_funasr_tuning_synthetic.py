"""End-to-end synthetic FunASR batch test; no network or paid model calls."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database.base import Base
from app.core.models.configuration import Environment, ModelConfiguration
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.security.crypto import encrypt_secret
from app.execution.http.contracts import ApiRequestResult
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_request_body import ApiRequestBody
from app.features.asr_evaluation.funasr_schemas import (
    FunAsrBindingCreate, FunAsrBindingUpdate, FunAsrGroundTruthCreate, FunAsrTuningCreate,
)
from app.features.asr_evaluation.models import AsrApiBinding, AsrAudio, AsrGroundTruthVersion, AsrTuningItem, AsrTuningSession
from app.features.asr_evaluation.runtime.funasr_worker import FunAsrTuningWorker
from app.features.asr_evaluation.services.funasr_tuning_service import (
    create_fun_asr_binding, create_ground_truth, create_tuning_session, get_tuning_session,
    retry_failed_tuning_items, update_fun_asr_binding,
)
from app.platform.environment_configuration.models.project_environment import ProjectEnvironment


def test_three_audio_serial_batch_keeps_one_parameter_set(monkeypatch):
    # Importing main registers feature-local models; only the isolated fixture's needed tables are created.
    import app.main  # noqa: F401

    names = {
        "user", "project", "model_configuration", "environment", "project_environment",
        "api_interface", "api_request_body", "asr_audio", "asr_audio_version",
        "asr_api_binding", "asr_ground_truth_version", "asr_tuning_session",
        "asr_tuning_round", "asr_tuning_item",
    }
    tables = [table for table in Base.metadata.sorted_tables if table.name in names]
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=tables)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    actor = User(username="synthetic-admin", role="admin", is_active=True)
    db.add(actor)
    db.flush()
    project = Project(name="synthetic-funasr", owner_id=actor.id)
    db.add(project)
    model = ModelConfiguration(
        domain_id="synthetic-text-model", label="Synthetic only", api_base="https://invalid.local/v1",
        model_name="fixture", is_enabled=True,
    )
    environment = Environment(name="synthetic", display_name="Synthetic", base_url="https://asr.invalid",
                              default_headers={}, is_active=True)
    db.add_all([model, environment])
    db.flush()
    db.add(ProjectEnvironment(project_id=project.id, environment_id=environment.id,
                              display_name="Synthetic", base_url="https://asr.invalid",
                              default_headers={}, is_active=True))
    interface = ApiInterface(project_id=project.id, name="FunASR fixture", method="POST",
        path="/api/v1/transcribe/paraformer/v2", version=1, source_hash="fixture-hash",
        content_type="application/json", status="ACTIVE")
    db.add(interface)
    db.flush()
    db.add(ApiRequestBody(interface_id=interface.id, body_type="json", content_type="application/json",
                          schema_json={"example": {"preset_spk_num": 1}}, raw_text=None))
    audios = []
    for index in range(3):
        audio = AsrAudio(project_id=project.id, name=f"fixture-{index + 1}",
            url_ciphertext=encrypt_secret(f"https://media.invalid/{index + 1}"),
            url_display=f"https://media.invalid/{index + 1}", content_version=1)
        db.add(audio)
        audios.append(audio)
    db.commit()
    project_id, model_id, interface_id = project.id, model.id, interface.id

    mapping = {"text_source": "full", "text_pointer": "/text"}
    binding = create_fun_asr_binding(db, FunAsrBindingCreate(
        project_id=project_id, api_interface_id=interface_id, environment_name="synthetic",
        response_mapping=mapping,
    ), actor)
    update_fun_asr_binding(db, binding["id"], FunAsrBindingUpdate(
        response_mapping=mapping, response_sample={"text": "fixture"},
    ), actor)
    for audio in audios:
        create_ground_truth(db, audio.id, FunAsrGroundTruthCreate(
            document={"text": f"样本{audio.id}"}, mapping=mapping,
        ), actor)
    session = create_tuning_session(db, FunAsrTuningCreate(
        project_id=project_id, binding_id=binding["id"], model_config_id=model_id,
        audio_ids=[audio.id for audio in audios], parameters={"preset_spk_num": 1, "merge_vad": False,
                                                               "noise_reduction_db": 0},
        allowed_parameters={"/noise_reduction_db": {"minimum": 0, "maximum": 10}},
        mode="AUTO_TUNE", max_rounds=2, max_asr_requests=6, max_ai_calls=8,
        idempotency_key="synthetic-batch-0001",
    ), actor)
    session_id = session["id"]
    assert session["status"] == "QUEUED"

    sent: list[dict] = []

    class FakeExecutor:
        def execute(self, _db, *, method, url, project_id, headers, json_body, timeout, max_response_bytes):
            assert method == "POST" and url.endswith("/api/v1/transcribe/paraformer/v2")
            assert project_id == project_id_expected
            sent.append(dict(json_body))
            result = ApiRequestResult()
            result.status_code = 200
            text = "变差候选" if json_body["noise_reduction_db"] == 6 else f"样本{json_body['audio'].rsplit('/', 1)[-1]}"
            if json_body["noise_reduction_db"] == 0 and json_body["audio"].endswith("/2"):
                response = {"body": text}
            else:
                response = {"text": text, "body": text}
            result.response_body = json.dumps(response, ensure_ascii=False)
            result.response_time_ms = 7
            return result

    project_id_expected = project_id

    class FakeLLM:
        def __init__(self, *_args, **_kwargs):
            self.last_usage = {"total_tokens": 9}

        def chat(self, system, _user):
            if "内容评审助手" in system:
                return json.dumps({"summary": "synthetic", "uncertainty": "", "findings": []})
            report_input = json.loads(_user)
            if report_input["round"] == 1:
                return json.dumps({"action": "propose", "summary": "synthetic candidate",
                    "common_findings": [], "changes": [{"path": "/noise_reduction_db", "old_value": 0,
                    "new_value": 6, "audio_ids": [audio.id for audio in audios],
                    "evidence_ids": ["ground_truth:full"], "rationale": "fixture only",
                    "expected_effect": "fixture only", "watch_metric": "micro_cer"}], "stop_reason": ""})
            return json.dumps({"action": "stop", "summary": "fixture only", "common_findings": [],
                               "changes": [], "stop_reason": "synthetic stop"})

    monkeypatch.setattr("app.llm.providers.openai_compatible.ProductionLLMProvider", FakeLLM)
    worker = FunAsrTuningWorker(db_factory=Session, executor=FakeExecutor(), poll_seconds=0.01)
    assert worker.tick() == 1
    db.expire_all()
    assert db.query(AsrTuningSession).filter_by(id=session_id).one().status == "FAILED"
    assert len(sent) == 3
    repaired_mapping = {"text_source": "full", "text_pointer": "/body"}
    update_fun_asr_binding(db, binding["id"], FunAsrBindingUpdate(
        response_mapping=repaired_mapping, response_sample={"body": "fixture"},
    ), actor)
    repaired = retry_failed_tuning_items(db, session_id, actor)
    assert repaired["status"] == "QUEUED"
    assert repaired["asr_requests_used"] == 3
    assert repaired["rounds"][0]["metrics"]["successful_samples"] == 3
    assert len(sent) == 3  # saved responses were remapped; the failed request was not resent
    assert worker.tick() == 1
    db.expire_all()
    assert db.query(AsrTuningSession).filter_by(id=session_id).one().status == "QUEUED"
    assert worker.tick() == 1
    db.expire_all()
    final = get_tuning_session(db, session_id, actor)
    assert final["status"] == "COMPLETED"
    assert final["asr_requests_used"] == 6 and final["ai_calls_used"] == 8
    assert len(final["rounds"]) == 2
    assert final["rounds"][0]["metrics"]["successful_samples"] == 3
    assert final["rounds"][0]["metrics"]["planned_samples"] == 3
    assert final["best_round_id"] == final["rounds"][0]["id"]
    assert final["rounds"][1]["accepted"] is False
    assert final["config_snapshot"]["binding"]["mapping_revisions"]
    assert len(sent) == 6
    for batch in (sent[:3], sent[3:]):
        assert len({json.dumps({k: v for k, v in body.items() if k != "audio"}, sort_keys=True) for body in batch}) == 1
        assert all(set(body) == {"audio", "preset_spk_num", "merge_vad", "noise_reduction_db"} for body in batch)
    assert all("答案" not in json.dumps(body, ensure_ascii=False) for body in sent)
    assert db.query(AsrGroundTruthVersion).count() == 3
    assert db.query(AsrTuningItem).filter_by(session_id=session_id, status="SUCCEEDED").count() == 6
    assert db.query(AsrTuningItem).filter_by(session_id=session_id, response_received=True).count() == 6
    assert db.query(AsrApiBinding).count() == 1
    assert db.query(AsrTuningSession).filter_by(id=session_id).one().best_round_id is not None
    session_row = db.query(AsrTuningSession).filter_by(id=session_id).one()
    session_row.status = "PAUSE_REQUESTED"
    session_row.lease_owner = "crashed-worker"
    session_row.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    db.commit()
    assert worker._claim_next() is None
    db.expire_all()
    assert db.query(AsrTuningSession).filter_by(id=session_id).one().status == "PAUSED"
    session_row = db.query(AsrTuningSession).filter_by(id=session_id).one()
    pending_item = db.query(AsrTuningItem).filter_by(session_id=session_id).first()
    pending_item.status = "SUBMITTING"
    pending_item.response_received = False
    session_row.status = "RUNNING"
    session_row.lease_owner = "crashed-worker"
    session_row.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    db.commit()
    assert worker._claim_next() is None
    db.expire_all()
    assert db.query(AsrTuningSession).filter_by(id=session_id).one().status == "RECONCILIATION_REQUIRED"
    assert db.query(AsrTuningItem).filter_by(id=pending_item.id).one().status == "RECONCILIATION_REQUIRED"
    assert len(sent) == 6
    db.close()
    engine.dispose()
