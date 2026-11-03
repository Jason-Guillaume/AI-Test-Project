"""说话人适配与验收阻断回归；所有服务与文本均使用隔离 SQLite 合成数据。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.models
from app.core.database.base import Base
from app.core.models.identity import Organization, OrganizationMember, User
from app.core.models.project import Project
from app.core.models.project import ProjectMember
from app.core.security.crypto import encrypt_secret
from app.features.asr_evaluation.alignment import align_triplet
from app.features.asr_evaluation.models import (
    AsrAudio, AsrComparison, AsrConnection, AsrFusionVersion, AsrJob, AsrModelRun,
    AsrParameterSet, AsrProcessingRun, AsrSchedule, AsrSpeaker, AsrSpeakerAssignment,
    AsrSpeakerTurn, AsrTranscriptSegment, AsrWorkItem,
)
from app.features.asr_evaluation.providers.generic_json import DiarizationJsonProvider, GenericJsonProvider
from app.features.asr_evaluation.runtime import worker as worker_module
from app.features.asr_evaluation.schemas import JobCreate
from app.features.asr_evaluation.services.assets_service import update_audio
from app.features.asr_evaluation.services.comparison_service import get_comparison, record_run_result
from app.features.asr_evaluation.services.diarization_service import (
    create_diarization_run, record_diarization_result, retry_processing_run,
)
from app.features.asr_evaluation.services.job_service import create_job
from app.features.asr_evaluation.services.job_service import list_jobs, runtime_status
from app.features.asr_evaluation.services.assets_service import list_audios
from app.features.asr_evaluation.services.comparison_service import list_comparisons
from app.features.asr_evaluation.schemas import DiarizationRunCreate
from app.features.asr_evaluation.services.segments_service import list_transcript_segments


@pytest.fixture
def sandbox():
    """建立独立内存库、最小项目与三方合成转写运行。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    names = {
        "user", "organization", "organization_member", "project", "project_member",
        "project_outbound_target", "model_configuration", "environment", "notification",
    }
    tables = [table for name, table in Base.metadata.tables.items()
              if name in names or name.startswith(("asr_", "model_"))]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    actor = User(username="asr-regression-only", role="admin", is_active=True)
    db.add(actor)
    db.flush()
    organization = Organization(name="asr-regression-only", owner_id=actor.id)
    db.add(organization)
    db.flush()
    project = Project(name="asr-regression-only", owner_id=actor.id, organization_id=organization.id)
    db.add(project)
    db.flush()
    audio = AsrAudio(
        project_id=project.id, name="合成回归音频",
        url_ciphertext=encrypt_secret("https://example.invalid/original.mp3"),
        url_display="https://example.invalid/original.mp3", duration_seconds=120, created_by=actor.id,
    )
    db.add(audio)
    connections = []
    for index, role in enumerate(["TEST", "REFERENCE", "REFERENCE"]):
        row = AsrConnection(
            project_id=project.id, name=f"合成转写-{index}", role=role, model_id="synthetic",
            endpoint_ciphertext=encrypt_secret("https://example.invalid/asr"),
            endpoint_display="https://example.invalid/asr", config_json={}, created_by=actor.id,
        )
        db.add(row)
        connections.append(row)
    db.flush()
    parameter_set = AsrParameterSet(
        project_id=project.id, connection_id=connections[0].id, name="baseline",
        parameters={}, definitions=[], created_by=actor.id,
    )
    db.add(parameter_set)
    db.commit()
    job = create_job(db, JobCreate(
        project_id=project.id, audio_ids=[audio.id], connection_ids=[row.id for row in connections],
        parameter_set_id=parameter_set.id,
    ), actor)
    yield db, factory, actor, audio, connections, parameter_set, job
    db.close()
    engine.dispose()


def test_nightly_schedule_triggers_job_and_keeps_plan_enabled(sandbox):
    """有效夜间计划到期后进入队列，不能因创建入口异常而停用。"""
    db, _, actor, audio, connections, parameter_set, _ = sandbox
    now = datetime.now(timezone.utc)
    schedule = AsrSchedule(
        project_id=audio.project_id, name="合成夜间计划", audio_ids=[audio.id],
        connection_ids=[row.id for row in connections], parameter_set_id=parameter_set.id,
        schedule_type="DAILY", timezone="Asia/Shanghai", local_time="01:00",
        next_run_at=now - timedelta(seconds=1), created_by=actor.id,
    )
    db.add(schedule)
    db.commit()
    worker_module.AsrWorker()._trigger_schedule(db, schedule, now)
    db.refresh(schedule)
    assert schedule.last_trigger_status == "QUEUED"
    assert schedule.enabled is True


@pytest.mark.parametrize(("test_text", "reference"), [
    ("会议结束。", "会议结束。请提交报告。"),
    ("甲。乙。", "一。二。三。四。"),
])
def test_alignment_round_trip_preserves_all_input_text(test_text, reference):
    """首尾插入与不等长替换都必须保持三路原文的完整可重建。"""
    rows, _ = align_triplet(test_text, reference, reference)
    assert "".join(row["test_text"] for row in rows) == test_text
    assert "".join(row["reference_a_text"] for row in rows) == reference
    assert "".join(row["reference_b_text"] for row in rows) == reference


def test_alignment_overflow_keeps_complete_tail_in_last_visible_block():
    """差异块上限触发降级时合并尾部原文，不能静默丢弃第 501 句。"""
    text = "".join(f"第{index}条。" for index in range(501))
    rows, degraded = align_triplet(text, text, text)
    assert degraded is True
    assert len(rows) == 500
    assert "".join(row["test_text"] for row in rows) == text


def test_result_write_failure_keeps_asr_queue_item_recoverable(sandbox):
    """写回失败时任务状态和工作项不分离提交，后续 Worker 仍能恢复。"""
    db, factory, *_ = sandbox
    with patch.object(worker_module, "SessionLocal", factory):
        worker = worker_module.AsrWorker()
        item_id, run_id, owner, generation, _ = worker._claim_next()
        with patch.object(worker_module, "record_run_result", side_effect=RuntimeError("synthetic write failure")):
            worker._finish(run_id, item_id, owner, generation, "FAILED", "synthetic failure")
    db.expire_all()
    assert db.get(AsrWorkItem, item_id) is not None
    assert db.get(AsrModelRun, run_id).status == "SUBMITTING"


def test_worker_restart_does_not_resubmit_uncertain_provider_submission(sandbox):
    """新 Worker 收到过期 SUBMITTING 租约时转人工核实，不重复提交请求。"""
    db, factory, _actor, _audio, _, _, job = sandbox
    with patch.object(worker_module, "SessionLocal", factory):
        first_worker = worker_module.AsrWorker(worker_id="synthetic-worker-before-restart")
        item_id, run_id, _owner, _generation, submitting = first_worker._claim_next()
        assert submitting is True
        item = db.get(AsrWorkItem, item_id)
        item.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

        restarted_worker = worker_module.AsrWorker(worker_id="synthetic-worker-after-restart")
        assert restarted_worker._claim_next() is None

    db.expire_all()
    assert db.get(AsrModelRun, run_id).status == "RECONCILIATION_REQUIRED"
    # Other model runs remain queued, so the aggregate batch stays RUNNING until
    # they finish; the interrupted run itself is clearly marked for reconciliation.
    assert db.get(AsrJob, job["id"]).status == "RUNNING"
    assert db.get(AsrWorkItem, item_id) is None


def test_worker_restart_resumes_poll_by_existing_remote_task_id(sandbox):
    """远端已有任务 ID 的运行在重启后继续轮询同一任务，不重新提交。"""
    db, factory, *_ = sandbox
    run = db.query(AsrModelRun).order_by(AsrModelRun.id).first()
    run.status = "REMOTE_RUNNING"
    run.remote_task_id = "synthetic-existing-task"
    item = db.query(AsrWorkItem).filter_by(run_id=run.id).one()
    item.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()

    with patch.object(worker_module, "SessionLocal", factory):
        restarted_worker = worker_module.AsrWorker(worker_id="synthetic-worker-after-restart")
        claim = restarted_worker._claim_next()

    assert claim is not None
    _, claimed_run_id, _, _, submitting = claim
    assert claimed_run_id == run.id
    assert submitting is False
    assert run.remote_task_id == "synthetic-existing-task"


def test_worker_process_heartbeat_distinguishes_alive_from_business_ready(sandbox):
    """进程新鲜但业务依赖未就绪时，不报告业务可接单。"""
    db, factory, *_ = sandbox
    db.add(worker_module.AsrWorkerHeartbeat(
        worker_id="synthetic-not-ready", last_seen_at=datetime.now(timezone.utc),
        active_count=0, business_ready=False,
    ))
    db.commit()
    with patch.object(worker_module, "SessionLocal", factory):
        worker = worker_module.AsrWorker(worker_id="synthetic-readiness-check")
        assert worker._business_dependencies_ready() is True
    status = runtime_status(db)
    assert status["process_alive"] is True
    assert status["business_ready"] is False


def test_expired_remote_poll_is_terminal_before_another_http_call(sandbox):
    """正常远端运行响应路径也受到 24 小时/200 次硬上限约束。"""
    db, factory, *_ = sandbox
    run = db.query(AsrModelRun).order_by(AsrModelRun.id).first()
    run.status = "REMOTE_RUNNING"
    run.remote_task_id = "synthetic-task"
    run.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    item = db.query(AsrWorkItem).filter_by(run_id=run.id).one()
    item.attempts = 250
    db.commit()
    with patch.object(worker_module, "SessionLocal", factory):
        worker = worker_module.AsrWorker()
        with patch.object(worker._provider, "poll", return_value={"state": "RUNNING"}) as poll:
            assert worker._claim_next() is None
            poll.assert_not_called()
    db.expire_all()
    assert db.get(AsrModelRun, run.id).status == "FAILED"
    assert db.query(AsrWorkItem).filter_by(run_id=run.id).first() is None


def test_historical_comparison_keeps_original_audio_version_after_url_update(sandbox):
    """修改音频 URL 不会把历史对比或媒体读取切换到新版本。"""
    db, _, actor, audio, _, _, job = sandbox
    runs = db.query(AsrModelRun).filter_by(job_id=job["id"]).all()
    for run in runs:
        record_run_result(db, run.id, status="SUCCEEDED", transcript="第一版录音文本。")
    comparison = db.query(AsrComparison).filter_by(job_id=job["id"]).one()
    update_audio(db, audio.id, name=None, url="https://example.invalid/replacement.mp3", duration_seconds=None, actor=actor)
    historical = get_comparison(db, comparison.id, actor)
    assert historical["audio"]["content_version"] == 1
    assert historical["audio"]["audio_version_id"] == runs[0].audio_version_id


def test_asr_list_pagination_reaches_37_jobs_101_audios_and_21_comparisons(sandbox):
    """隔离合成 37/101/21 条记录，验证服务端末页覆盖而不是只取第一页。"""
    db, _, actor, audio, _, _, source_job = sandbox
    project_id = audio.project_id

    db.add_all([
        AsrJob(project_id=project_id, status="COMPLETED", config_snapshot={"audio_ids": []}, created_by=actor.id)
        for _ in range(36)
    ])
    db.add_all([
        AsrAudio(
            project_id=project_id, name=f"synthetic-audio-{index}",
            url_ciphertext=encrypt_secret(f"https://example.invalid/audio-{index}.mp3"),
            url_display=f"https://example.invalid/audio-{index}.mp3", created_by=actor.id,
        )
        for index in range(100)
    ])
    db.add_all([
        AsrComparison(
            project_id=project_id, job_id=source_job["id"], audio_id=audio.id,
            version=version, status="COMPLETE", summary={"diff_blocks": 0},
        )
        for version in range(1, 22)
    ])
    db.commit()

    job_pages = [list_jobs(db, project_id, actor, page=page, page_size=20) for page in range(1, 3)]
    final_jobs = list_jobs(db, project_id, actor, page=2, page_size=20)
    assert sum(len(page["items"]) for page in job_pages) == 37
    assert final_jobs["total"] == 37 and final_jobs["page"] == 2 and len(final_jobs["items"]) == 17

    audio_pages = [list_audios(db, project_id, actor, page=page, page_size=20) for page in range(1, 7)]
    assert sum(len(page["items"]) for page in audio_pages) == 101
    assert audio_pages[-1]["total"] == 101 and len(audio_pages[-1]["items"]) == 1
    assert audio_pages[-1]["items"][0]["id"] == audio.id

    comparison_pages = [list_comparisons(db, project_id, actor, page=page, page_size=20) for page in range(1, 3)]
    assert sum(len(page["items"]) for page in comparison_pages) == 21
    assert comparison_pages[-1]["total"] == 21 and len(comparison_pages[-1]["items"]) == 1


@pytest.mark.parametrize(("role", "may_create"), [("member", True), ("viewer", False)])
def test_asr_project_member_permissions_keep_history_readable_and_writes_scoped(sandbox, role, may_create):
    """普通成员可按授权创建，项目只读成员保留历史读取但不能排队任务。"""
    db, _, _owner, audio, connections, parameter_set, _source_job = sandbox
    member = User(username=f"synthetic-{role}-member", role="test", is_active=True)
    db.add(member)
    db.flush()
    db.add(ProjectMember(
        project_id=audio.project_id, user_id=member.id, role=role, created_by=_owner.id,
    ))
    project = db.get(Project, audio.project_id)
    if project.organization_id is not None:
        db.add(OrganizationMember(
            organization_id=project.organization_id, user_id=member.id, role="member",
        ))
    db.commit()

    history = list_jobs(db, audio.project_id, member)
    assert history["total"] == 1
    body = JobCreate(
        project_id=audio.project_id, audio_ids=[audio.id],
        connection_ids=[row.id for row in connections], parameter_set_id=parameter_set.id,
    )
    if may_create:
        assert create_job(db, body, member)["status"] == "QUEUED"
    else:
        with pytest.raises(HTTPException) as error:
            create_job(db, body, member)
        assert error.value.status_code == 403


def test_asr_project_switch_reads_only_selected_project_data(sandbox):
    """模拟管理员在两个项目间切换，列表查询严格按当前 project_id 隔离。"""
    db, _, admin, audio, _, _, _ = sandbox
    other_project = Project(name="asr-regression-switch-project", owner_id=admin.id)
    db.add(other_project)
    db.flush()
    other_audio = AsrAudio(
        project_id=other_project.id, name="other-project-synthetic-audio",
        url_ciphertext=encrypt_secret("https://example.invalid/other-project.mp3"),
        url_display="https://example.invalid/other-project.mp3", created_by=admin.id,
    )
    db.add(other_audio)
    db.commit()

    assert list_audios(db, audio.project_id, admin)["total"] == 1
    switched = list_audios(db, other_project.id, admin)
    assert switched["total"] == 1
    assert switched["items"][0]["id"] == other_audio.id


def test_diarization_provider_keeps_native_zero_ids_overlap_and_text_segments():
    """区间-only 与带文本响应共用协议，数字 0、重叠、声道及置信度均不丢失。"""
    provider = DiarizationJsonProvider(executor=object())
    response = SimpleNamespace(
        response_truncated=False, transport_error_kind=None, error_message=None, status_code=200,
        response_body=json.dumps({"segments": [
            {"id": "turn-a", "start": 1.2, "end": 3.4, "speaker_id": 0, "channel": 1, "confidence": 0.97},
            {"id": "turn-b", "start": 3.0, "end": 4.2, "speaker_id": "spk_1", "text": "你好", "confidence": 0.8},
        ]}),
        response_headers={}, response_time_ms=4,
    )
    result = provider._parse_response(response, {
        "response_mapping": {
            "segments_pointer": "/segments", "start_pointer": "/start", "end_pointer": "/end",
            "speaker_pointer": "/speaker_id", "segment_id_pointer": "/id", "segment_text_pointer": "/text",
            "channel_pointer": "/channel", "confidence_pointer": "/confidence", "time_unit": "seconds",
        },
    }, submitting=True)
    assert result["turns"][0]["source_speaker_id"] == "0"
    assert result["turns"][0]["start_ms"] == 1200
    assert result["turns"][0]["channel"] == "1"
    assert result["turns"][0]["confidence"] == pytest.approx(0.97)
    assert result["turns"][1]["text"] == "你好"
    assert result["turns"][0]["end_ms"] > result["turns"][1]["start_ms"]


def test_diarization_provider_accepts_explicit_empty_no_speech_result():
    """有效空区间数组表示没有检测到语音，不作为接口错误处理。"""
    provider = DiarizationJsonProvider(executor=object())
    response = SimpleNamespace(
        response_truncated=False, transport_error_kind=None, error_message=None, status_code=200,
        response_body='{"segments": []}', response_headers={}, response_time_ms=1,
    )
    result = provider._parse_response(response, {
        "response_mapping": {"segments_pointer": "/segments"},
    }, submitting=True)
    assert result["state"] == "SUCCEEDED"
    assert result["turns"] == []


def test_asr_segment_adapter_preserves_exact_unicode_offsets_and_native_metadata():
    """ASR 原生段 ID、数字说话人标签、声道、置信度和 code point 偏移一并保留。"""
    provider = GenericJsonProvider(executor=object())
    result = provider._segments({"segments": [{
        "id": "seg-1", "text": "🙂好", "start": 1.25, "end": 2.5, "speaker": 0,
        "confidence": 0.8, "channel": 0, "words": [{"text": "好", "start": 1.5, "end": 1.8}],
    }]}, {
        "segments_pointer": "/segments", "segment_id_pointer": "/id", "segment_text_pointer": "/text",
        "start_pointer": "/start", "end_pointer": "/end", "speaker_pointer": "/speaker",
        "confidence_pointer": "/confidence", "channel_pointer": "/channel", "word_times_pointer": "/words",
    }, "前🙂好后")
    assert result[0]["source_segment_id"] == "seg-1"
    assert result[0]["native_speaker_id"] == "0"
    assert result[0]["channel"] == "0"
    assert result[0]["confidence"] == pytest.approx(0.8)
    assert result[0]["start_offset"] == 1
    assert result[0]["end_offset"] == 3
    assert result[0]["word_times"][0]["text"] == "好"


def _make_diarization_connection(db, project_id: int, actor_id: int) -> AsrConnection:
    """建立只有 JSON 参数映射、无厂商凭据的合成说话人连接。"""
    connection = AsrConnection(
        project_id=project_id, name="合成说话人模型", role=None, task_type="DIARIZATION",
        model_id="synthetic-diarization", endpoint_ciphertext=encrypt_secret("https://example.invalid/diarize"),
        endpoint_display="https://example.invalid/diarize", config_json={"parameter_definitions": []},
        created_by=actor_id,
    )
    db.add(connection)
    db.commit()
    return connection


def test_single_diarization_run_is_deduplicated_and_fused_to_asr_segments(sandbox):
    """同版说话人任务默认只建一次，并保留原生 ID、重叠与 ASR 时间关联。"""
    db, _, actor, audio, _, _, job = sandbox
    connection = _make_diarization_connection(db, audio.project_id, actor.id)
    asr_run = db.query(AsrModelRun).filter_by(job_id=job["id"]).order_by(AsrModelRun.id).first()
    record_run_result(db, asr_run.id, status="SUCCEEDED", transcript="你好", segments=[{
        "segment_index": 0, "source_segment_id": "asr-seg-1", "text": "你好",
        "start_ms": 1000, "end_ms": 2500, "start_offset": 0, "end_offset": 2,
        "native_speaker_id": "native-0", "confidence": 0.91, "channel": "left",
    }])
    body = DiarizationRunCreate(connection_id=connection.id, parameters={})
    first = create_diarization_run(db, audio.id, asr_run.audio_version_id, body, actor)
    second = create_diarization_run(db, audio.id, asr_run.audio_version_id, body, actor)
    assert first["id"] == second["id"]
    assert db.query(AsrProcessingRun).filter_by(task_type="DIARIZATION").count() == 1

    result = record_diarization_result(db, first["id"], timeline="original_audio", model_version="fixture-1",
        duration_ms=12, raw_response={"provider": "synthetic"}, turns=[
            {"source_speaker_id": "0", "start_ms": 1000, "end_ms": 1900, "text": "你", "channel": "left", "confidence": 0.8},
            {"source_speaker_id": "spk_1", "start_ms": 1800, "end_ms": 2500, "text": "好", "channel": "right", "confidence": 0.7},
        ])
    db.flush()
    assert db.query(AsrSpeaker).filter_by(result_id=result.id).count() == 2
    assert db.query(AsrSpeakerTurn).filter_by(result_id=result.id).count() == 2
    fusion = db.query(AsrFusionVersion).filter_by(model_run_id=asr_run.id, diarization_result_id=result.id).one()
    assert fusion.status == "COMPLETE"
    assignments = db.query(AsrSpeakerAssignment).filter_by(fusion_version_id=fusion.id).all()
    assert len(assignments) == 2
    assert {row.assignment_status for row in assignments} == {"OVERLAPPED"}
    read_model = list_transcript_segments(db, asr_run.id, actor)
    segment = read_model["items"][0]
    assert segment["source_segment_id"] == "asr-seg-1"
    assert segment["native_speaker_id"] == "native-0"
    assert segment["start_ms"] == 1000 and segment["end_ms"] == 2500
    assert all(item["id"] for item in segment["assignments"])


def test_missing_asr_timing_remains_unaligned_and_speaker_retry_does_not_clone_asr(sandbox):
    """无时间戳全文保持可读但不归属；说话人失败重试仅生成新处理运行。"""
    db, _, actor, audio, _, _, job = sandbox
    connection = _make_diarization_connection(db, audio.project_id, actor.id)
    asr_run = db.query(AsrModelRun).filter_by(job_id=job["id"]).order_by(AsrModelRun.id).first()
    record_run_result(db, asr_run.id, status="SUCCEEDED", transcript="同一句重复。同一句重复。", segments=[
        {"text": "同一句重复。", "start_ms": None, "end_ms": None, "start_offset": 0, "end_offset": 6},
        {"text": "同一句重复。", "start_ms": None, "end_ms": None, "start_offset": 7, "end_offset": 13},
    ])
    created = create_diarization_run(
        db, audio.id, asr_run.audio_version_id,
        DiarizationRunCreate(connection_id=connection.id, parameters={}), actor,
    )
    result = record_diarization_result(db, created["id"], timeline="original_audio", model_version=None,
        duration_ms=1, raw_response={}, turns=[
            {"source_speaker_id": "speaker", "start_ms": 1000, "end_ms": 2000},
        ])
    fusion = db.query(AsrFusionVersion).filter_by(model_run_id=asr_run.id, diarization_result_id=result.id).one()
    assert fusion.status == "UNALIGNED"
    assignments = db.query(AsrSpeakerAssignment).filter_by(fusion_version_id=fusion.id).all()
    assert len(assignments) == 2
    assert {row.assignment_status for row in assignments} == {"UNALIGNED"}
    db.query(AsrProcessingRun).filter_by(id=created["id"]).update({"status": "FAILED"})
    db.commit()
    retried = retry_processing_run(db, created["id"], actor)
    assert retried["id"] != created["id"]
    assert db.query(AsrModelRun).filter_by(job_id=job["id"]).count() == 3
