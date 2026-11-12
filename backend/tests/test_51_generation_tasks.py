"""P6：真实隔离 PostgreSQL + 受控模型替身，覆盖持久化调度和审核入库。"""
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest

from app.agents.models import AgentDefinition
from app.core.config import settings
from app.core.database.session import SessionLocal
from app.core.models.identity import User
from app.features.test_management.models.case_generation import CaseDraft, CaseGenerationBatch
from app.features.test_management.services import generation_tasks as tasks
from app.orchestration.tasks.models import TaskRun, TaskWorkItem, TaskAttempt, TaskSchedulerControl
from app.orchestration.tasks.runtime.worker import TaskWorker
from app.orchestration.tasks.runtime.lease_service import claim_work, recover_expired
from app.orchestration.tasks.runtime.handlers import case_generation as handler
from app.llm import LLMError
from tests.conftest import unique


class Stub:
    """禁止外网；可按模块注入失败和并行屏障。"""
    failures = set()
    barrier = None
    calls = []
    review_fail = False
    last_usage = {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}

    def __init__(self, db, snapshot, policy, before_request):
        """保存模块与事务检查回调。"""
        self.module = snapshot.get('module', 'review')
        self.db = db
        self.before = before_request

    def generate_structured(self, system, user_content, schema=None, *, kind=None, validator=None, **kwargs):
        """模型边界断言没有数据库事务；失败不带任何真实模型流量。"""
        self.before()
        assert not self.db.in_transaction()
        Stub.calls.append(self.module)
        if self.module in Stub.failures or (self.module == 'review' and Stub.review_fail):
            raise LLMError('LLM_TRANSPORT_ERROR', 'controlled', retryable=True)
        if Stub.barrier and self.module != 'review':
            Stub.barrier.wait(timeout=10)
        value = {'summary': '受控审阅', 'gaps': []} if self.module == 'review' else {'cases': [{
            'title': unique(self.module), 'priority': 'P1', 'requirement': '需求', 'preconditions': ['已登录'],
            'test_data': ['合成数据'], 'steps': ['操作'], 'expected_results': ['成功'], 'coverage': ['边界'], 'needs_confirmation': []}]}
        return value


@pytest.fixture
def setup(api, admin, db, monkeypatch):
    """停应用轮询，用手动 Worker 驱动；每个测试创建独立项目与可控模型。"""
    from app.main import task_worker
    was_running = task_worker.is_running
    task_worker.stop()
    monkeypatch.setattr(settings, 'CASE_GENERATION_MAX_ATTEMPTS', 1)
    monkeypatch.setattr(handler, 'GenerationProvider', Stub)
    Stub.calls, Stub.failures, Stub.barrier, Stub.review_fail = [], set(), None, False
    project = api.post('/projects', username=admin, json={'name': unique('P6'), 'description': 'test'}).json()['id']
    model = api.post('/model-configs', username=admin, json={'label': unique('stub'), 'provider': 'openai-compatible',
        'api_base': 'http://127.0.0.1:1/v1', 'model_name': 'test-only', 'api_key': 'test-dummy', 'is_enabled': True}).json()['id']
    agent = next(row for row in db.query(AgentDefinition).filter_by(workflow_template='case_generation').all() if row.child_agent_ids)
    actor = db.query(User).filter_by(username=admin).one()
    control = db.get(TaskSchedulerControl, 1)
    original_limit = control.max_concurrent_runs
    control.max_concurrent_runs = 5
    db.commit()
    worker = TaskWorker(db_factory=SessionLocal, owner=unique('worker'))
    body = {'agent_id': agent.id, 'direction': 'API', 'requirements': '生成 P6 用例', 'include_security': True,
            'model_config_id': model, 'request_key': unique('request')}
    yield api, admin, project, body, actor.id, worker
    # 清理本测试专属项目并恢复共享调度状态，允许任意测试顺序运行。
    from app.core.models.project import Project
    with SessionLocal() as cleanup:
        own_project = cleanup.get(Project, project)
        if own_project:
            cleanup.delete(own_project)
        cleanup.get(TaskSchedulerControl, 1).max_concurrent_runs = original_limit
        cleanup.commit()
    if was_running:
        task_worker.start()


def submit(setup):
    """提交新异步生成，不等待任何模型调用。"""
    api, admin, project, body, _, _ = setup
    result = api.post(f'/projects/{project}/case-generation-tasks', username=admin, json=body)
    assert result.status_code == 202, result.text
    return result.json()


def detail(setup, batch):
    """从真实状态接口读取进度。"""
    api, admin, *_ = setup
    return api.get(f'/case-generation-batches/{batch["id"]}/task', username=admin).json()


def drain(worker):
    """执行所有立即可领取项，避免隐式网络或后台等待。"""
    for _ in range(20):
        if worker.tick() == 0:
            return
    raise AssertionError('任务未收敛')


def test_submit_idempotent_and_review_import(setup):
    """P6.1：HTTP 立即返回、重复键复用、模块独立保存，结果仍可审核入库。"""
    started = time.monotonic()
    batch = submit(setup)
    assert time.monotonic() - started < 3
    assert batch['task_id'] and batch['task_run_id'] and batch['status'] == 'QUEUED'
    assert Stub.calls == []
    assert submit(setup)['id'] == batch['id']
    api, admin, project, body, _, worker = setup
    changed = dict(body, requirements='different')
    assert api.post(f'/projects/{project}/case-generation-tasks', username=admin, json=changed).status_code == 409
    assert worker.tick() == 1
    saved = api.get(f'/case-generation-batches/{batch["id"]}', username=admin).json()
    assert len(saved['drafts']) == 1
    drain(worker)
    status = detail(setup, batch)
    assert status['status'] == 'COMPLETED' and status['run_status'] == 'SUCCEEDED'
    assert status['completed'] == status['total'] == 3
    assert status['observability_status'] in {'DISABLED', 'UNVERIFIED'}
    assert status['modules'][0]['model_revision']
    assert len(status['trace_id']) == 32
    assert status['execution_root_run_id'] == batch['task_run_id']
    assert all(item['trace_id'] == status['trace_id'] for item in status['modules'])
    with SessionLocal() as identity_db:
        assert all(identity_db.get(TaskRun, item['task_run_id']).execution_root_run_id == batch['task_run_id'] for item in status['modules'])
    assert status['events']
    accepted = api.post(f'/case-drafts/{saved["drafts"][0]["id"]}/accept', username=admin)
    assert accepted.status_code == 200
    case = api.get(f'/test-cases/{accepted.json()["test_case_id"]}', username=admin).json()
    assert case['status'] == 'DRAFT'


def test_parallel_partial_failure_retry_preserves_review(setup):
    """P6.2/P6.3：两个已租约领取模块可并行，部分失败不覆盖已审核草稿。"""
    batch = submit(setup)
    Stub.barrier = threading.Barrier(2)
    claims = [claim_work(db_factory=SessionLocal, owner=f'parallel-{i}', lease_seconds=60) for i in range(2)]
    assert all(claims)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda pair: TaskWorker(db_factory=SessionLocal, owner=f'parallel-{pair[0]}')._run_claimed(pair[1]), enumerate(claims)))
    Stub.barrier = None
    assert set(Stub.calls) == {'api', 'security'}
    drain(setup[-1])
    assert detail(setup, batch)['status'] == 'COMPLETED'


def test_partial_and_review_retry(setup):
    """仅失败模块重试；独立 Review 失败也可重试，成功结果只生成一次。"""
    Stub.failures = {'security'}
    batch = submit(setup)
    drain(setup[-1])
    assert detail(setup, batch)['status'] == 'PARTIAL_FAILED'
    api, admin, *_ = setup
    saved = api.get(f'/case-generation-batches/{batch["id"]}', username=admin).json()['drafts'][0]
    assert api.post(f'/case-drafts/{saved["id"]}/accept', username=admin).status_code == 200
    Stub.failures = set()
    Stub.review_fail = True
    assert api.post(f'/case-generation-batches/{batch["id"]}/retry', username=admin).status_code == 200
    drain(setup[-1])
    assert detail(setup, batch)['status'] == 'PARTIAL_FAILED'
    Stub.review_fail = False
    assert api.post(f'/case-generation-batches/{batch["id"]}/retry', username=admin).status_code == 200
    drain(setup[-1])
    result = api.get(f'/case-generation-batches/{batch["id"]}', username=admin).json()
    assert result['status'] == 'COMPLETED' and len(result['drafts']) == 2
    assert result['drafts'][0]['status'] == 'ACCEPTED'
    assert Stub.calls.count('api') == 1 and Stub.calls.count('security') == 2


def test_cancel_preserves_completed_module(setup):
    """取消不删除成功草稿，待执行模块不会调用模型。"""
    batch = submit(setup)
    setup[-1].tick()
    api, admin, *_ = setup
    result = api.post(f'/case-generation-batches/{batch["id"]}/cancel', username=admin)
    assert result.status_code == 200 and result.json()['status'] == 'CANCELLED'
    assert len(result.json()['drafts']) == 1
    assert setup[-1].tick() == 0


def test_expired_lease_late_result_and_restart(setup, monkeypatch):
    """P6.4：重启恢复未完成项，旧代次迟到结果不可写入。"""
    monkeypatch.setattr(settings, 'CASE_GENERATION_MAX_ATTEMPTS', 3)
    batch = submit(setup)
    old = claim_work(db_factory=SessionLocal, owner='old', lease_seconds=60)
    with SessionLocal() as db:
        run = db.get(TaskRun, old.run_id)
        work = db.get(TaskWorkItem, old.work_item_id)
        claim = (run.id, work.id, old.attempt_id, old.owner, work.attempt_count, batch['id'])
        run.lease_expires_at = datetime.now() - timedelta(seconds=1)
        db.commit()
    assert recover_expired(db_factory=SessionLocal) == 1
    with SessionLocal() as db:
        handler.finish(db, claim, {'cases': [], 'status': 'SUCCEEDED'}, None)
        assert db.query(CaseDraft).filter_by(batch_id=batch['id']).count() == 0
        work = db.get(TaskWorkItem, old.work_item_id)
        work.available_at = datetime.now() - timedelta(seconds=1)
        db.commit()
    drain(TaskWorker(db_factory=SessionLocal, owner='restarted'))
    assert detail(setup, batch)['status'] == 'COMPLETED'
    assert Stub.calls.count('api') == 1


def test_cancel_running_safe_boundary(setup, monkeypatch):
    """已发出的模型调用结束后保存草稿，再安全取消所有待办。"""
    batch = submit(setup)
    entered, release = threading.Event(), threading.Event()
    original = Stub.generate_structured

    def blocked(self, *args, **kwargs):
        """阻塞可控模型，确保取消发生在真实执行边界内。"""
        entered.set()
        assert release.wait(10)
        # 已发出请求的返回不再次执行取消检查。
        before, self.before = self.before, lambda: self.db.commit()
        try:
            return original(self, *args, **kwargs)
        finally:
            self.before = before

    monkeypatch.setattr(Stub, 'generate_structured', blocked)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(setup[-1].tick)
        assert entered.wait(10)
        api, admin, *_ = setup
        cancelled = api.post(f'/case-generation-batches/{batch["id"]}/cancel', username=admin).json()
        assert cancelled['status'] == 'CANCEL_REQUESTED'
        release.set()
        assert future.result(15) == 1
    result = api.get(f'/case-generation-batches/{batch["id"]}', username=admin).json()
    assert result['status'] == 'CANCELLED' and len(result['drafts']) == 1
    assert detail(setup, batch)['run_status'] == 'CANCELLED'


def test_timeout_backoff_and_attempt_limit(setup, monkeypatch):
    """模块时限触发有界指数退避；耗尽后终态失败并允许 Review 聚合。"""
    monkeypatch.setattr(settings, 'CASE_GENERATION_MAX_ATTEMPTS', 2)
    monkeypatch.setattr(settings, 'CASE_GENERATION_MODULE_TIMEOUT_SECONDS', 1)
    batch = submit(setup)
    original = Stub.generate_structured

    def timeout(self, *args, **kwargs):
        """用受控异常模拟网络超时，不联系外部模型。"""
        if self.module != 'review':
            raise LLMError('MODEL_TIMEOUT', 'controlled timeout', retryable=True)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Stub, 'generate_structured', timeout)
    drain(setup[-1])
    with SessionLocal() as db:
        works = tasks.batch_works(db, db.get(CaseGenerationBatch, batch['id']))
        for work in works:
            if work.kind == 'CASE_GENERATE':
                assert work.status == 'PENDING' and work.attempt_count == 1
                assert work.available_at > datetime.now()
                work.available_at = datetime.now() - timedelta(seconds=1)
        db.commit()
    drain(setup[-1])
    assert detail(setup, batch)['status'] == 'FAILED'
    assert all(item['attempts'] == 2 for item in detail(setup, batch)['modules'] if item['module'] != 'review')


def test_project_user_limits_and_cross_project_isolation(setup):
    """同项目可容纳两个任务，超额被拒；未授权账号不可查看、取消或重试。"""
    first = submit(setup)
    api, admin, project, body, *_ = setup
    second = api.post(f'/projects/{project}/case-generation-tasks', username=admin, json=dict(body, request_key=unique('two')))
    assert second.status_code == 202
    third = api.post(f'/projects/{project}/case-generation-tasks', username=admin, json=dict(body, request_key=unique('three')))
    assert third.status_code == 409
    outsider = unique('outside')
    assert api.register(outsider).status_code == 201
    from tests.conftest import DEFAULT_PASSWORD
    api.login(outsider, DEFAULT_PASSWORD)
    assert api.get(f'/case-generation-batches/{first["id"]}/task', username=outsider).status_code == 404
    for action in ('cancel', 'retry'):
        assert api.post(f'/case-generation-batches/{first["id"]}/{action}', username=outsider).status_code in (403, 404)
    assert api.post(f'/projects/{project}/case-generation-tasks', username=outsider, json=body).status_code in (403, 404)
    drain(setup[-1])
    assert detail(setup, first)['status'] == 'COMPLETED'


def test_duplicate_concurrent_requests(setup):
    """并发重复提交通过用户锁和唯一约束只创建一个批次与任务。"""
    api, admin, project, body, actor_id, _ = setup

    def create(_):
        """独立 Session 模拟并发 HTTP 创建事务。"""
        from app.features.test_management.schemas.generation import GenerationTaskRequest
        with SessionLocal() as db:
            return tasks.submit(db, project, GenerationTaskRequest(**body), db.get(User, actor_id)).id

    with ThreadPoolExecutor(2) as pool:
        ids = list(pool.map(create, range(2)))
    assert ids[0] == ids[1]
    drain(setup[-1])


def test_generation_provider_budget_timeout_and_no_transaction(setup, monkeypatch):
    """真实 Provider 配置边界：网络替身检查超时、预算预留和事务释放。"""
    # 使用真实生成 Provider 的 _post 预留逻辑，只替换最底层 HTTP。
    monkeypatch.undo()
    from app.orchestration.tasks.runtime.handlers.case_generation import GenerationProvider
    from app.llm.providers import ProductionLLMProvider
    from app.platform.model_configuration.services.model_config_service import model_configuration_revision
    from app.core.models.configuration import ModelConfiguration
    batch = submit(setup)
    claim = claim_work(db_factory=SessionLocal, owner='budget', lease_seconds=60)
    with SessionLocal() as db:
        run = db.get(TaskRun, claim.run_id)
        work = db.get(TaskWorkItem, claim.work_item_id)
        snapshot = run.input_snapshot['agent']
        policy = dict(run.input_snapshot['policy'], call_token_limit=100, _claim=(run.id, work.id, claim.attempt_id, 'budget', work.attempt_count, batch['id']))
        provider = GenerationProvider(db, snapshot, policy, lambda: db.commit())
        config = provider._load_config(snapshot['model_config_id'])
        assert config.timeout <= policy['module_timeout'] and config.max_tokens == 100
        db.commit()
        class ControlledResponse:
            status_code = 200

            @staticmethod
            def json():
                return {'usage': {}}

        controlled_response = ControlledResponse()

        def post(self, url, *, json, headers, timeout):
            """HTTP 替身验证调用边界，绝不发送真实模型请求。"""
            assert not db.in_transaction()
            return controlled_response

        monkeypatch.setattr(ProductionLLMProvider, '_post', post)
        assert provider._post('http://127.0.0.1:1', json={'messages': [{'content': 'data'}], 'max_tokens': 100}, headers={}, timeout=1) is controlled_response
        attempt = db.get(TaskAttempt, claim.attempt_id, populate_existing=True)
        assert attempt.checkpoint_json['reserved_tokens'] > 100
        db.commit()
        provider.policy['token_budget'] = 1
        with pytest.raises(LLMError, match='预算'):
            provider._post('http://127.0.0.1:1', json={'messages': [{'content': 'data'}], 'max_tokens': 100}, headers={}, timeout=1)
    # 取消该受控执行并由过期租约收敛，不再运行真实 Provider。
    api, admin, *_ = setup
    api.post(f'/case-generation-batches/{batch["id"]}/cancel', username=admin)
    with SessionLocal() as db:
        db.get(TaskRun, claim.run_id).lease_expires_at = datetime.now() - timedelta(seconds=1)
        db.commit()
    recover_expired(db_factory=SessionLocal)


def test_public_snapshot_and_project_cascade(setup):
    """公共任务详情不泄露冻结 Prompt；删除项目时关联数据按既有规则级联。"""
    batch = submit(setup)
    drain(setup[-1])
    with SessionLocal() as db:
        from app.orchestration.tasks.services.serializers import TaskSerializers
        from app.core.models.project import Project
        run = db.get(TaskRun, batch['task_run_id'])
        value = TaskSerializers.run_response(run)['input_snapshot']
        assert 'instruction' not in str(value) and 'skills' not in value and 'request' not in value
        assert value['batch_id'] == batch['id']
        db.delete(db.get(Project, setup[2]))
        db.commit()
        assert db.get(CaseGenerationBatch, batch['id']) is None


def test_retry_cannot_bypass_task_capacity(setup):
    """失败任务重新排队也必须服从当前项目和用户活跃任务额度。"""
    Stub.failures = {'security'}
    batch = submit(setup)
    drain(setup[-1])
    api, admin, project, body, *_ = setup
    queued = []
    for _ in range(2):
        response = api.post(f'/projects/{project}/case-generation-tasks', username=admin, json=dict(body, request_key=unique('capacity')))
        assert response.status_code == 202
        queued.append(response.json())
    assert api.post(f'/case-generation-batches/{batch["id"]}/retry', username=admin).status_code == 409
    for item in queued:
        api.post(f'/case-generation-batches/{item["id"]}/cancel', username=admin)
    assert api.post(f'/case-generation-batches/{batch["id"]}/retry', username=admin).status_code == 200
    Stub.failures = set()
    drain(setup[-1])
    assert detail(setup, batch)['status'] == 'COMPLETED'


def test_module_and_global_concurrency_gates(setup, monkeypatch):
    """数据库全局额度和批次并发配置都不能被多个 Worker 绕过。"""
    monkeypatch.setattr(settings, 'CASE_GENERATION_MODULE_CONCURRENCY', 1)
    batch = submit(setup)
    first = claim_work(db_factory=SessionLocal, owner='gate', lease_seconds=60)
    assert first
    assert claim_work(db_factory=SessionLocal, owner='other', lease_seconds=60) is None
    api, admin, project, body, *_ = setup
    other = api.post(f'/projects/{project}/case-generation-tasks', username=admin, json=dict(body, request_key=unique('gate'))).json()
    with SessionLocal() as db:
        db.get(TaskSchedulerControl, 1).max_concurrent_runs = 1
        db.commit()
    assert claim_work(db_factory=SessionLocal, owner='other', lease_seconds=60) is None
    TaskWorker(db_factory=SessionLocal, owner='gate')._run_claimed(first)
    drain(setup[-1])
    assert detail(setup, batch)['status'] == 'COMPLETED'
    assert detail(setup, other)['status'] == 'COMPLETED'


def test_worker_stop_does_not_duplicate_live_executor(setup, monkeypatch):
    """在途请求未结束时再次 start 不得清除停止标记或复制执行池。"""
    from app.orchestration.tasks.runtime import worker as runtime
    entered, release = threading.Event(), threading.Event()
    claims = iter([object()])
    monkeypatch.setattr(runtime, 'claim_work', lambda **kwargs: next(claims, None))
    monkeypatch.setattr(runtime, 'recover_expired', lambda **kwargs: 0)
    worker = TaskWorker(db_factory=SessionLocal, owner='stop-check', poll_interval_seconds=0.2)

    def blocked(claim):
        """模拟已经发出的不可中断模型请求。"""
        entered.set()
        release.wait(10)

    monkeypatch.setattr(worker, '_run_claimed', blocked)
    worker.start()
    try:
        assert entered.wait(5)
        original_thread = worker._thread
        worker.stop(timeout_seconds=0.1)
        worker.start()
        assert worker._thread is original_thread and worker._stop_event.is_set()
    finally:
        release.set()
        worker.stop(timeout_seconds=5)
    assert not worker.is_running
