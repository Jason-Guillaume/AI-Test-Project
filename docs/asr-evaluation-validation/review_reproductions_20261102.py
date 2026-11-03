"""ASR 验收回归复现：仅使用内存 SQLite 和合成数据，不访问业务数据库或云端接口。"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.models
from app.core.database.base import Base
from app.core.models.identity import User, Organization
from app.core.models.project import Project
from app.core.security.crypto import encrypt_secret
from app.features.asr_evaluation.alignment import align_triplet
from app.features.asr_evaluation.models import (
    AsrAudio, AsrConnection, AsrParameterSet, AsrSchedule, AsrJob, AsrModelRun, AsrWorkItem,
)
from app.features.asr_evaluation.schemas import JobCreate
from app.features.asr_evaluation.services.job_service import create_job
from app.features.asr_evaluation.services.comparison_service import record_run_result, get_comparison
from app.features.asr_evaluation.services.assets_service import update_audio
from app.features.asr_evaluation.runtime import worker as worker_module


@pytest.fixture
def sandbox():
    """建立只含平台核心及 ASR 表的内存库，返回合成任务和独立 Session 工厂。"""
    engine = create_engine('sqlite:///:memory:', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    names = {'user', 'organization', 'organization_member', 'project', 'project_member',
             'project_outbound_target', 'model_configuration', 'environment', 'notification'}
    tables = [table for name, table in Base.metadata.tables.items()
              if name in names or name.startswith('asr_')]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    actor = User(username='review-only', role='admin', is_active=True)
    db.add(actor)
    db.flush()
    org = Organization(name='review-only', owner_id=actor.id)
    db.add(org)
    db.flush()
    project = Project(name='review-only', owner_id=actor.id, organization_id=org.id)
    db.add(project)
    db.flush()
    audio = AsrAudio(project_id=project.id, name='合成验收音频',
                     url_ciphertext=encrypt_secret('https://example.org/original.mp3'),
                     url_display='https://example.org/original.mp3', duration_seconds=2400, created_by=actor.id)
    db.add(audio)
    connections = []
    for index, role in enumerate(['TEST', 'REFERENCE', 'REFERENCE']):
        row = AsrConnection(project_id=project.id, name=f'合成接口-{index}', role=role,
                            model_id='synthetic', endpoint_ciphertext=encrypt_secret('https://example.org/asr'),
                            endpoint_display='https://example.org/asr', config_json={}, created_by=actor.id)
        db.add(row)
        connections.append(row)
    db.flush()
    params = AsrParameterSet(project_id=project.id, connection_id=connections[0].id,
                             name='baseline', parameters={}, definitions=[], created_by=actor.id)
    db.add(params)
    db.commit()
    payload = JobCreate(project_id=project.id, audio_ids=[audio.id],
                        connection_ids=[row.id for row in connections], parameter_set_id=params.id)
    job = create_job(db, payload, actor)
    yield db, factory, actor, audio, connections, params, job
    db.close()
    engine.dispose()


def test_nightly_schedule_creates_job(sandbox):
    """有效到期计划应创建新批次，而不是被吞掉 NameError 后停用。"""
    db, _, actor, audio, connections, params, _ = sandbox
    now = datetime.now(timezone.utc)
    schedule = AsrSchedule(project_id=audio.project_id, name='合成夜间计划', audio_ids=[audio.id],
                           connection_ids=[row.id for row in connections], parameter_set_id=params.id,
                           schedule_type='DAILY', timezone='Asia/Shanghai', local_time='01:00',
                           next_run_at=now - timedelta(seconds=1), created_by=actor.id)
    db.add(schedule)
    db.commit()
    worker_module.AsrWorker()._trigger_schedule(db, schedule, now)
    db.refresh(schedule)
    assert schedule.last_trigger_status == 'QUEUED', (schedule.last_trigger_status, schedule.enabled)


def test_alignment_preserves_appended_reference_text():
    """两家参考在末尾多识别的内容必须保留，否则最关键漏识别会被隐藏。"""
    reference = '会议结束。请提交报告。'
    rows, degraded = align_triplet('会议结束。', reference, reference)
    assert ''.join(row['reference_a_text'] for row in rows) == reference, (rows, degraded)


def test_alignment_preserves_unequal_replacement():
    """参考替换块比待测多句时仍应完整保留两侧文本。"""
    reference = '一。二。三。四。'
    rows, degraded = align_triplet('甲。乙。', reference, reference)
    assert ''.join(row['reference_a_text'] for row in rows) == reference, (rows, degraded)


def test_block_limit_preserves_unprocessed_tail():
    """分块超限降级时必须保留尾部全文，不可只保留前 500 块。"""
    text = ''.join(f'第{index}条。' for index in range(501))
    rows, degraded = align_triplet(text, text, text)
    rebuilt = ''.join(row['test_text'] for row in rows)
    assert rebuilt == text, (len(rows), degraded, rebuilt[-30:], text[-30:])


def test_failed_result_persistence_keeps_recoverable_work(sandbox):
    """保存终态失败时应保留可恢复工作项，不能先提交删除再写结果。"""
    db, factory, *_ = sandbox
    with patch.object(worker_module, 'SessionLocal', factory):
        worker = worker_module.AsrWorker()
        item_id, run_id, owner, generation, _ = worker._claim_next()
        with patch.object(worker_module, 'record_run_result', side_effect=RuntimeError('合成结果落库故障')):
            worker._finish(run_id, item_id, owner, generation, 'FAILED', '合成失败')
        db.expire_all()
        assert db.get(AsrWorkItem, item_id) is not None, ('工作项已删除', db.get(AsrModelRun, run_id).status)


def test_successful_pending_poll_obeys_deadline(sandbox):
    """持续返回运行中的远端任务也必须执行 24 小时和次数上限。"""
    db, factory, *_ = sandbox
    run = db.query(AsrModelRun).order_by(AsrModelRun.id).first()
    run.status = 'REMOTE_RUNNING'
    run.remote_task_id = 'synthetic-task'
    run.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    item = db.query(AsrWorkItem).filter_by(run_id=run.id).one()
    item.attempts = 250
    db.commit()
    with patch.object(worker_module, 'SessionLocal', factory):
        worker = worker_module.AsrWorker()
        with patch.object(worker._provider, 'poll', return_value={'state': 'RUNNING', 'response_time_ms': 1}) as poll:
            assert worker._claim_next() is None
            poll.assert_not_called()
    db.expire_all()
    assert db.get(AsrModelRun, run.id).status == 'FAILED'


def test_historical_comparison_does_not_switch_audio_version(sandbox):
    """音频链接更新后，历史对比必须仍指向原版本而非新链接。"""
    db, _, actor, audio, _, _, job = sandbox
    runs = db.query(AsrModelRun).filter_by(job_id=job['id']).all()
    for run in runs:
        record_run_result(db, run.id, status='SUCCEEDED', transcript='第一版录音文本。')
    from app.features.asr_evaluation.models import AsrComparison
    comparison = db.query(AsrComparison).filter_by(job_id=job['id']).one()
    update_audio(db, audio.id, name=None, url='https://example.org/replacement.mp3',
                 duration_seconds=None, actor=actor)
    result = get_comparison(db, comparison.id, actor)
    assert result['audio']['content_version'] == 1, result['audio']
