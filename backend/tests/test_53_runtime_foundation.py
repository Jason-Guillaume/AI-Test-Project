"""运行底座首批验收：真实隔离 PostgreSQL 验证执行身份、饥饿、截止与预算；不访问真实模型。"""
from datetime import datetime, timedelta

import httpx
import pytest
from sqlalchemy.exc import IntegrityError

from app.agents.models import AgentSession
from app.features.test_management.models.case_generation import CaseGenerationBatch
from app.core.database.session import SessionLocal
from app.orchestration.tasks.models import Task, TaskRun, TaskWorkItem, TaskWorkItemDependency, TaskAttempt, TaskAgentInstance
from app.orchestration.tasks.runtime.lease_service import claim_work, renew_lease, recover_expired
from app.orchestration.tasks.runtime.completion_service import complete_work
from app.orchestration.tasks.runtime.handlers.case_generation import GenerationProvider
from app.llm.providers import ProductionLLMProvider
from tests.test_51_generation_tasks import setup as generation_setup, submit, detail, drain, Stub


@pytest.fixture(autouse=True)
def restore_scheduler(api):
    """手动驱动测试结束后恢复原调度线程，避免影响后续依赖后台 Worker 的测试。"""
    from app.main import task_worker
    running = task_worker.is_running
    yield
    if running:
        task_worker.start()


@pytest.fixture
def setup(generation_setup):
    """清理本用例故障注入的在途租约；共享测试库不能残留占用全局槽位的伪执行。"""
    yield generation_setup
    api, admin, project, *_ = generation_setup
    with SessionLocal() as db:
        batches = [row.id for row in db.query(CaseGenerationBatch).filter_by(project_id=project)]
    for batch_id in batches:
        api.post(f'/case-generation-batches/{batch_id}/cancel', username=admin)
    with SessionLocal() as db:
        runs = db.query(TaskRun).join(Task, Task.id == TaskRun.task_id).filter(Task.project_id == project).all()
        for run in runs:
            if run.lease_expires_at:
                run.lease_expires_at = datetime.now() - timedelta(seconds=1)
        db.commit()
    recover_expired(db_factory=SessionLocal)
    with SessionLocal() as db:
        for run in db.query(TaskRun).join(Task, Task.id == TaskRun.task_id).filter(Task.project_id == project):
            # 故意注入“work已终态但run仍持租约”的用例须显式清理异常测试状态。
            run.lease_owner = run.lease_expires_at = None
        for task in db.query(Task).filter(Task.project_id == project, Task.task_mode != 'CASE_GENERATION'):
            db.delete(task)
        db.commit()


def test_execution_identity_and_independent_sessions(setup):
    """一个生成根关联全部模块实例，各模块拥有独立会话且不公开冻结指令。"""
    batch = submit(setup)
    status = detail(setup, batch)
    with SessionLocal() as db:
        runs = db.query(TaskRun).filter_by(task_id=status['task_id']).all()
        assert {run.execution_root_run_id for run in runs} == {batch['task_run_id']}
        assert len({run.trace_id for run in runs}) == 1
        assert len(status['trace_id']) == 32
        assert len({item['agent_run_id'] for item in status['modules']}) == len(runs)
        assert len({item['agent_session_id'] for item in status['modules']}) == len(runs)
        root_instance = db.query(TaskAgentInstance).filter_by(task_run_id=batch['task_run_id']).one()
        children = db.query(TaskAgentInstance).filter(TaskAgentInstance.parent_agent_instance_id == root_instance.id).all()
        assert len(children) == len(runs) - 1
        assert all('instruction' not in instance.config_snapshot for instance in [root_instance, *children])
    drain(setup[-1])
    with SessionLocal() as db:
        assert {s.status for s in db.query(AgentSession).filter(AgentSession.task_run_id.in_([run.id for run in runs]))} == {'COMPLETED'}
    assert {item['trace_id'] for item in detail(setup, batch)['modules']} == {status['trace_id']}


def test_more_than_twenty_blocked_candidates_do_not_starve_ready_work(setup):
    """大量前置未完成依赖不能挡住后面的就绪模块。"""
    batch = submit(setup)
    with SessionLocal() as db:
        task = Task(project_id=setup[2], created_by=setup[4], title='依赖等待', goal='受控测试')
        db.add(task)
        db.flush()
        run = TaskRun(task_id=task.id, run_number=1, goal_snapshot='依赖等待')
        db.add(run)
        db.flush()
        blocker = TaskWorkItem(task_run_id=run.id, work_key='blocker', kind='PLAN', sequence=-100,
            idempotency_key='blocker', available_at=datetime.now() + timedelta(hours=1))
        db.add(blocker)
        db.flush()
        for i in range(25):
            work = TaskWorkItem(task_run_id=run.id, work_key=f'blocked:{i}', kind='PLAN', sequence=-100,
                idempotency_key=f'blocked:{i}')
            db.add(work)
            db.flush()
            db.add(TaskWorkItemDependency(work_item_id=work.id, depends_on_id=blocker.id))
        db.commit()
    claim = claim_work(db_factory=SessionLocal, owner='ready', lease_seconds=60)
    assert claim
    with SessionLocal() as db:
        assert db.get(TaskWorkItem, claim.work_item_id).kind == 'CASE_GENERATE'
        assert db.get(TaskRun, claim.run_id).task_id == batch['task_id']


@pytest.mark.parametrize('invalid', ['expired', 'attempt_terminal', 'work_terminal', 'deadline'])
def test_heartbeat_does_not_revive_invalid_claim(setup, invalid):
    """即使 owner 和 generation 相同，终态、截止或已过期执行也不能续租。"""
    submit(setup)
    claim = claim_work(db_factory=SessionLocal, owner='heartbeat', lease_seconds=60)
    with SessionLocal() as db:
        run = db.get(TaskRun, claim.run_id)
        if invalid == 'expired':
            run.lease_expires_at = datetime.now() - timedelta(seconds=1)
        elif invalid == 'attempt_terminal':
            db.get(TaskAttempt, claim.attempt_id).status = 'FAILED'
        elif invalid == 'work_terminal':
            db.get(TaskWorkItem, claim.work_item_id).status = 'SUCCEEDED'
        else:
            db.get(TaskAttempt, claim.attempt_id).deadline_at = datetime.now() - timedelta(seconds=1)
        before = run.lease_expires_at
        db.commit()
    assert not renew_lease(claim, db_factory=SessionLocal, owner='heartbeat', lease_seconds=300)
    with SessionLocal() as db:
        assert db.get(TaskRun, claim.run_id).lease_expires_at == before


def test_heartbeat_caps_lease_at_attempt_deadline(setup):
    """健康执行可续租，但租约不能越过请求截止时间。"""
    submit(setup)
    claim = claim_work(db_factory=SessionLocal, owner='bounded', lease_seconds=60)
    assert renew_lease(claim, db_factory=SessionLocal, owner='bounded', lease_seconds=1000)
    with SessionLocal() as db:
        assert db.get(TaskRun, claim.run_id).lease_expires_at <= db.get(TaskAttempt, claim.attempt_id).deadline_at


def test_queued_deadline_converges_without_calling_model(setup):
    """排队任务总截止后无需启动模型即可终结所有模块与协调根。"""
    batch = submit(setup)
    with SessionLocal() as db:
        for run in db.query(TaskRun).filter_by(task_id=batch['task_id']):
            run.deadline_at = datetime.now() - timedelta(seconds=1)
        db.commit()
    # 只验证过期恢复；共享隔离库中其他测试的就绪任务不属于本断言范围。
    recover_expired(db_factory=SessionLocal)
    assert Stub.calls == []
    status = detail(setup, batch)
    assert all(item['attempts'] == 0 for item in status['modules'])
    assert status['status'] == 'FAILED' and status['completed'] == status['total']
    assert all(item['error_code'] == 'TASK_DEADLINE_EXCEEDED' for item in status['modules'])


def test_expired_claim_cannot_commit_pending_business_changes(setup):
    """通用收尾对仍同 owner 的过期租约也回滚，防止恢复前空窗写入。"""
    batch = submit(setup)
    claim = claim_work(db_factory=SessionLocal, owner='stale', lease_seconds=60)
    with SessionLocal() as db:
        run = db.get(TaskRun, claim.run_id)
        run.lease_expires_at = datetime.now() - timedelta(seconds=1)
        db.commit()
        task = db.get(Task, run.task_id)
        original = task.title
        task.title = '迟到写入'
        work, attempt = db.get(TaskWorkItem, claim.work_item_id), db.get(TaskAttempt, claim.attempt_id)
        complete_work(db, task, run, work, attempt, None)
    with SessionLocal() as db:
        assert db.get(Task, batch['task_id']).title == original
        assert db.get(TaskWorkItem, claim.work_item_id).status == 'RUNNING'


def test_multiple_http_calls_account_known_and_unknown_usage(setup, monkeypatch):
    """同 Attempt 多调用分开累计，已知 usage 释放余量，无 usage 保留保守预留。"""
    batch = submit(setup)
    claim = claim_work(db_factory=SessionLocal, owner='calls', lease_seconds=60)
    responses = iter([httpx.Response(200, json={'usage': {'prompt_tokens': 5, 'completion_tokens': 7, 'total_tokens': 12}}),
                      httpx.Response(503, json={'error': '受控错误'})])
    with SessionLocal() as db:
        run, work = db.get(TaskRun, claim.run_id), db.get(TaskWorkItem, claim.work_item_id)
        policy = dict(run.input_snapshot['policy'], call_token_limit=100,
            _claim=(run.id, work.id, claim.attempt_id, claim.owner, work.attempt_count, batch['id']))
        provider = GenerationProvider(db, run.input_snapshot['agent'], policy, lambda: db.commit())
        db.commit()

        def post(self, url, *, json, headers, timeout):
            """仅返回受控 HTTP 响应，并断言网络边界无事务且 timeout 有截止限制。"""
            assert not db.in_transaction()
            assert 0 < timeout <= policy['module_timeout']
            return next(responses)

        monkeypatch.setattr(ProductionLLMProvider, '_post', post)
        for _ in range(2):
            provider._post('http://127.0.0.1:1', json={'messages': [{'content': 'synthetic'}], 'max_tokens': 100}, headers={}, timeout=600)
        checkpoint = db.get(TaskAttempt, claim.attempt_id, populate_existing=True).checkpoint_json
        calls = checkpoint['model_calls']
        assert len(calls) == len({call['call_id'] for call in calls}) == 2
        assert calls[0]['usage_status'] == 'KNOWN' and calls[0]['accounted_tokens'] == 12
        assert calls[1]['usage_status'] == 'UNKNOWN'
        assert checkpoint['reserved_tokens'] == 12 + calls[1]['reserved_tokens']


def test_execution_root_cannot_reference_another_task(setup):
    """数据库复合外键兜底阻止跨任务执行根拼接，提交失败不污染原运行。"""
    batch = submit(setup)
    with SessionLocal() as db:
        task = Task(project_id=setup[2], created_by=setup[4], title='其他任务', goal='受控测试')
        db.add(task)
        db.flush()
        run = TaskRun(task_id=task.id, run_number=1, goal_snapshot='其他', execution_root_run_id=batch['task_run_id'])
        db.add(run)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
