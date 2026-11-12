"""隔离 PostgreSQL 的 ASR 内容评审接口与 Worker 合成回归。

测试使用随机测试库和临时产物目录；模型与音频均为合成数据，不访问外部服务。
"""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.config import settings
from app.core.database.session import SessionLocal
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import User
from app.core.security.crypto import encrypt_secret
from app.features.asr_evaluation.models import AsrAudio, AsrConnection, AsrModelRun, AsrParameterSet, AsrWorkItem
from app.features.asr_evaluation.runtime.worker import AsrWorker
from app.features.asr_evaluation.schemas import JobCreate
from app.features.asr_evaluation.services.content_review_service import claim_review, execute_review
from app.features.asr_evaluation.services.job_service import create_job


def test_content_review_api_and_worker_use_migrated_postgres(api, admin, db, tmp_path, monkeypatch):
    """通过真实鉴权接口排队，在隔离 PostgreSQL 上领取、保存并下载合成报告。"""
    monkeypatch.setattr(settings, "ASR_ARTIFACT_DIR", str(tmp_path))
    project_response = api.post("/projects", username=admin, json={"name": f"asr-review-{uuid4().hex[:8]}"})
    assert project_response.status_code == 201, project_response.text
    project_id = project_response.json()["id"]
    actor = db.query(User).filter_by(username=admin).one()
    audio = AsrAudio(project_id=project_id, name="合成音频", url_ciphertext=encrypt_secret("https://example.invalid/a.wav"),
                     url_display="https://example.invalid/a.wav", duration_seconds=3, created_by=actor.id)
    db.add(audio)
    connections = []
    for index, role in enumerate(("TEST", "REFERENCE", "REFERENCE")):
        item = AsrConnection(project_id=project_id, name=f"合成模型-{index}", role=role, model_id="fake",
            endpoint_ciphertext=encrypt_secret("https://example.invalid/asr"), endpoint_display="https://example.invalid/asr",
            config_json={}, created_by=actor.id)
        db.add(item)
        connections.append(item)
    db.flush()
    parameters = AsrParameterSet(project_id=project_id, connection_id=connections[0].id, name="合成参数",
                                 parameters={}, definitions=[], created_by=actor.id)
    model = ModelConfiguration(domain_id=f"asr-review-{uuid4().hex}", label="合成文本模型",
        provider="openai-compatible", api_base="https://example.invalid/v1", model_name="fake",
        is_enabled=True, created_by=actor.id)
    db.add_all([parameters, model])
    db.commit()
    job = create_job(db, JobCreate(project_id=project_id, audio_ids=[audio.id],
        connection_ids=[item.id for item in connections], parameter_set_id=parameters.id), actor)
    run = db.query(AsrModelRun).filter_by(job_id=job["id"], role="TEST").one()
    work = db.query(AsrWorkItem).filter_by(run_id=run.id).one()
    work.lease_owner, work.lease_generation = "synthetic-asr", 1
    work.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=2)
    run.status = "SUBMITTING"
    db.commit()

    class SyntheticAsr:
        """返回已解析的合成 ASR 响应，不访问真实转写服务。"""
        def submit(self, *_args, **_kwargs):
            return {"state": "SUCCEEDED", "transcript": "这是合成内容。", "segments": [], "response_time_ms": 1,
                    "response_kind": "RESPONSE_SYNC", "response_capture": {"body": {"text": "这是合成内容。"},
                    "redacted": False, "redaction_version": "asr-response-redaction-1"}}

    worker = AsrWorker(worker_id="synthetic-asr-worker")
    worker._provider = SyntheticAsr()
    worker._execute_claim(work.id, run.id, "synthetic-asr", 1, True)
    db.expire_all()
    assert db.get(AsrModelRun, run.id).status == "SUCCEEDED"
    artifacts = api.get(f"/asr/runs/{run.id}/evaluation-artifacts", username=admin)
    assert artifacts.status_code == 200 and artifacts.json()["raw_response_available"] is True
    response = api.post(f"/asr/runs/{run.id}/content-review-jobs?model_config_id={model.id}", username=admin)
    assert response.status_code == 202, response.text
    review_id = response.json()["id"]

    class SyntheticProvider:
        """返回固定结构，不创建网络连接。"""
        def __init__(self, *_args, **_kwargs):
            pass

        def chat(self, *_args):
            return json.dumps({"verdict": "reviewed", "findings": [{"dimension": "可读性", "description": "合成观察。",
                "evidence": [{"id": f"run:{run.id}:transcript", "quote": "合成内容"}]}]}, ensure_ascii=False)

    import app.llm.providers.openai_compatible as provider_module
    monkeypatch.setattr(provider_module, "ProductionLLMProvider", SyntheticProvider)
    with SessionLocal() as worker_session:
        claim = claim_review(worker_session, "synthetic-pg-worker")
    assert claim and claim[0] == review_id
    execute_review(*claim)
    completed = api.get(f"/asr/content-review-jobs/{review_id}", username=admin)
    assert completed.status_code == 200, completed.text
    report = completed.json()
    assert report["status"] == "SUCCEEDED" and report["coverage_status"] == "COMPLETE"
    assert report["chunks"][0]["result"]["findings"][0]["evidence"][0]["quote"] == "合成内容"
    download = api.get(f"/asr/evaluation-artifacts/{report['report_artifact_id']}", username=admin)
    assert download.status_code == 200 and download.json()["status"] == "SUCCEEDED"
