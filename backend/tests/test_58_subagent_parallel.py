"""通用任务中的叶子子 Agent 以有界 LangGraph fan-out/fan-in 并行运行。"""

from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

import app.agents.runtime.subagents as subagents
from app.llm.contracts import LLMError
from app.orchestration.tasks.runtime.handlers.planning import reject_failed_children
from app.tools.contracts import ToolCallContext
from app.tools.dispatcher import ToolDispatchError, dispatch_tool


@contextmanager
def _no_trace(**_kwargs):
    yield None


def test_subagents_fan_out_concurrently_and_keep_declared_order(monkeypatch):
    monkeypatch.setattr(subagents, "runtime_call_observation", _no_trace)
    barrier = Barrier(2)
    lock = Lock()
    statuses: dict[int, list[str]] = {}

    class Provider:
        def __init__(self, child_id: int):
            self.child_id = child_id

        def chat(self, _system: str, _prompt: str) -> str:
            barrier.wait(timeout=3)
            return f"建议 {self.child_id}"

    children = [
        {"id": 101, "name": "支付 Agent", "version": 2},
        {"id": 102, "name": "退款 Agent", "version": 4},
    ]

    def update_status(child, status):
        with lock:
            statuses.setdefault(child["id"], []).append(status)

    result = subagents.run_subagent_graph(
        children, "只读任务上下文", lambda child: Provider(child["id"]),
        update_status, max_concurrency=2,
    )

    assert [item["name"] for item in result] == ["支付 Agent", "退款 Agent"]
    assert [item["summary"] for item in result] == ["建议 101", "建议 102"]
    assert [item["status"] for item in result] == ["SUCCEEDED", "SUCCEEDED"]
    assert statuses == {101: ["RUNNING", "SUCCEEDED"], 102: ["RUNNING", "SUCCEEDED"]}


def test_one_failed_child_does_not_discard_successful_siblings(monkeypatch):
    monkeypatch.setattr(subagents, "runtime_call_observation", _no_trace)
    statuses: dict[int, list[str]] = {}

    class Provider:
        def __init__(self, child_id: int):
            self.child_id = child_id

        def chat(self, _system: str, _prompt: str) -> str:
            if self.child_id == 101:
                raise RuntimeError("must not be exposed")
            return "已完成独立分析"

    children = [
        {"id": 101, "name": "支付 Agent", "version": 2},
        {"id": 102, "name": "退款 Agent", "version": 4},
    ]
    result = subagents.run_subagent_graph(
        children, "只读任务上下文", lambda child: Provider(child["id"]),
        lambda child, status: statuses.setdefault(child["id"], []).append(status),
        max_concurrency=2,
    )

    assert [item["status"] for item in result] == ["FAILED", "SUCCEEDED"]
    assert result[0]["error_code"] == "RuntimeError"
    assert result[0]["retryable"] is False
    assert result[0]["error_class"] == "PERMANENT"
    assert "must not be exposed" not in result[0]["summary"]
    assert statuses == {101: ["RUNNING", "FAILED"], 102: ["RUNNING", "SUCCEEDED"]}


def test_completed_child_checkpoint_is_reused_without_provider_call(monkeypatch):
    monkeypatch.setattr(subagents, "runtime_call_observation", _no_trace)
    provider_calls = []
    persisted = []
    children = [{
        "id": 101, "name": "支付 Agent", "version": 2,
        "input_fingerprint": "stable-input",
    }]

    def forbidden_provider(_child):
        provider_calls.append(True)
        raise AssertionError("completed child must not be called again")

    result = subagents.run_subagent_graph(
        children, "同一任务上下文", forbidden_provider,
        completed_results={101: {
            "input_fingerprint": "stable-input",
            "summary": "已持久化的分析结果",
            "knowledge_sources": [{"chunk_id": 77, "version_id": 5}],
        }},
        result_callback=lambda child, checkpoint: persisted.append((child["id"], checkpoint["summary"])),
    )

    assert provider_calls == []
    assert persisted == [(101, "已持久化的分析结果")]
    assert result == [{
        "name": "支付 Agent", "version": 2, "status": "SUCCEEDED",
        "summary": "已持久化的分析结果",
        "knowledge_sources": [{"chunk_id": 77, "version_id": 5}],
    }]


def test_blank_output_and_legacy_blank_checkpoint_are_retried_without_repeating_sibling(monkeypatch):
    monkeypatch.setattr(subagents, "runtime_call_observation", _no_trace)
    children = [{"id": ident, "input_fingerprint": str(ident)} for ident in (1, 2)]
    calls, statuses, checkpoints = [], [], {}

    def provider(child):
        calls.append(child["id"])
        return SimpleNamespace(chat=lambda *_: " \n\t " if child["id"] == 1 else "兄弟节点已完成")

    result = subagents.run_subagent_graph(
        children, "冻结输入", provider,
        lambda child, status: statuses.append((child["id"], status)),
        completed_results={1: {"input_fingerprint": "1", "summary": " \n "}},
        result_callback=lambda child, result: checkpoints.update({child["id"]: result}),
    )
    assert result[0]["status"] == "FAILED"
    assert result[0]["error_code"] == "EMPTY_SUBAGENT_OUTPUT"
    assert result[0]["retryable"]
    assert (1, "SUCCEEDED") not in statuses and 1 not in checkpoints
    assert sorted(calls) == [1, 2]

    def retry(child):
        calls.append(child["id"])
        return SimpleNamespace(chat=lambda *_: "  已恢复分析  ")

    calls.clear()
    result = subagents.run_subagent_graph(children, "冻结输入", retry, completed_results=checkpoints)
    assert calls == [1]
    assert [item["summary"] for item in result] == ["已恢复分析", "兄弟节点已完成"]


def test_checkpoint_with_different_input_fingerprint_runs_again(monkeypatch):
    monkeypatch.setattr(subagents, "runtime_call_observation", _no_trace)
    calls = []
    children = [{
        "id": 101, "name": "支付 Agent", "version": 2,
        "input_fingerprint": "new-input",
        "runtime_metadata": {"attempt_id": 22},
    }]

    class Provider:
        def chat(self, _system: str, _prompt: str) -> str:
            calls.append(True)
            return "按新上下文生成的分析"

    result = subagents.run_subagent_graph(
        children, "更新后的任务上下文", lambda _child: Provider(),
        completed_results={101: {
            "input_fingerprint": "old-input",
            "summary": "不可复用的旧分析",
        }},
    )

    assert calls == [True]
    assert result[0]["summary"] == "按新上下文生成的分析"


def test_model_response_before_checkpoint_failure_is_retried_at_least_once(monkeypatch):
    """模型已返回但成功检查点提交失败时，恢复会再次调用并可完成；计费窗口明确为 at-least-once。"""
    monkeypatch.setattr(subagents, "runtime_call_observation", _no_trace)
    provider_calls = []
    children = [{
        "id": 101, "name": "支付 Agent", "version": 2,
        "input_fingerprint": "same-input",
    }]

    class Provider:
        def chat(self, _system: str, _prompt: str) -> str:
            provider_calls.append(True)
            return "模型已返回的结果"

    def interrupted_checkpoint(_child, _checkpoint):
        raise RuntimeError("checkpoint store interrupted")

    interrupted = subagents.run_subagent_graph(
        children, "同一任务上下文", lambda _child: Provider(),
        completed_results={}, result_callback=interrupted_checkpoint,
    )
    assert interrupted[0]["status"] == "FAILED"
    assert provider_calls == [True]

    recovered = subagents.run_subagent_graph(
        children, "同一任务上下文", lambda _child: Provider(),
        completed_results={}, result_callback=lambda _child, _checkpoint: None,
    )
    assert recovered[0]["status"] == "SUCCEEDED"
    assert recovered[0]["summary"] == "模型已返回的结果"
    assert provider_calls == [True, True]


def test_retryable_child_failure_is_classified_without_leaking_the_message(monkeypatch):
    monkeypatch.setattr(subagents, "runtime_call_observation", _no_trace)

    class Provider:
        def chat(self, _system: str, _prompt: str) -> str:
            raise LLMError("RATE_LIMIT", "secret upstream body", retryable=True)

    result = subagents.run_subagent_graph(
        [{"id": 7, "name": "接口 Agent", "version": 1}],
        "任务上下文",
        lambda _child: Provider(),
    )

    assert result[0]["status"] == "FAILED"
    assert result[0]["error_code"] == "RATE_LIMIT"
    assert result[0]["retryable"] is True
    assert "secret" not in result[0]["summary"]


def test_failed_child_blocks_successful_plan_status():
    with pytest.raises(LLMError) as permanent:
        reject_failed_children([
            {"status": "FAILED", "name": "支付 Agent", "retryable": False},
            {"status": "SUCCEEDED", "name": "退款 Agent"},
        ])
    assert permanent.value.code == "SUBAGENT_FAILED"
    assert permanent.value.retryable is False
    assert "支付 Agent" in str(permanent.value)

    with pytest.raises(LLMError) as retryable:
        reject_failed_children([
            {"status": "FAILED", "name": "接口 Agent", "retryable": True},
        ])
    assert retryable.value.retryable is True
    reject_failed_children([{"status": "SUCCEEDED", "name": "接口 Agent"}])


def test_disabled_tool_is_rejected_before_handler_runs():
    class Query:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return SimpleNamespace(is_enabled=False)

    class DB:
        def query(self, _model):
            return Query()

    with pytest.raises(ToolDispatchError, match="已停用"):
        dispatch_tool(
            "case_generation.generate_api", channel="fixed",
            context=ToolCallContext(db=DB()), requirements="不应执行",
        )


def test_expired_task_deadline_blocks_tool_before_handler_runs():
    class Query:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return None

    class DB:
        def query(self, _model):
            return Query()

        def get(self, _model, _ident):
            return SimpleNamespace(deadline_at=datetime.now() - timedelta(seconds=1))

    with pytest.raises(ToolDispatchError, match="截止时间"):
        dispatch_tool(
            "case_generation.generate_api", channel="fixed",
            context=ToolCallContext(db=DB(), task_run_id=1), requirements="不应执行",
        )


def test_tool_outcomes_survive_outer_rollback_and_keep_trusted_run_references(api, admin, db, monkeypatch):
    from sqlalchemy.orm import Session
    from app.core.config import settings
    from app.orchestration.tasks.models import RuntimeEventFact, Task, TaskAttempt, TaskRun, TaskWorkItem
    from app.tools import registry
    from app.tools.contracts import ToolBinding
    from app.tools.models import ToolDefinitionOverride
    from tests.conftest import unique

    project = api.post('/projects', username=admin, json={'name': unique('tool-facts')}).json()['id']
    task = Task(project_id=project, title='工具审计', goal='隔离验证', status='RUNNING')
    db.add(task)
    db.flush()
    run = TaskRun(task_id=task.id, run_number=1, goal_snapshot=task.goal, status='RUNNING')
    db.add(run)
    db.flush()
    work = TaskWorkItem(task_run_id=run.id, work_key='audit', kind='AUDIT', status='RUNNING', idempotency_key=unique('tool'))
    db.add(work)
    db.flush()
    attempt = TaskAttempt(work_item_id=work.id, attempt_number=1, owner='test')
    override = ToolDefinitionOverride(tool_key='runtime.test_tool_audit', is_enabled=False)
    db.add_all([attempt, override])
    db.commit()
    attempt_id = attempt.id
    context = ToolCallContext(db=db, project_id=project, task_id=task.id, task_run_id=run.id,
        execution_root_run_id=run.id, work_item_id=work.id, attempt_id=attempt_id)
    calls = []

    def handler(action, secret):
        calls.append(action)
        if action == 'fail':
            raise ValueError(secret)
        return 'done'

    monkeypatch.setitem(registry._BINDINGS, override.tool_key, ToolBinding(
        override.tool_key, handler, 'read', frozenset({'fixed'}), 'runtime_only',
    ))
    monkeypatch.setattr(settings, 'TOOL_CALL_TIMEOUT_SECONDS', 2)
    payload = {'action': 'blocked', 'secret': 'SYNTHETIC_SECRET_CONTENT'}
    with pytest.raises(ToolDispatchError):
        dispatch_tool(override.tool_key, channel='fixed', context=context, **payload)
    db.rollback()
    override.is_enabled = True
    attempt.deadline_at = datetime.now() - timedelta(seconds=2)
    db.commit()
    with pytest.raises(ToolDispatchError):
        dispatch_tool(override.tool_key, channel='fixed', context=context, **payload)
    db.rollback()
    attempt.deadline_at = None
    db.commit()
    assert calls == []

    # Production handlers can hold locks on the same attempt referenced by the event.
    db.query(TaskAttempt).filter_by(id=attempt_id).with_for_update().one()
    with pytest.raises(ValueError):
        dispatch_tool(override.tool_key, channel='fixed', context=context, action='fail', secret=payload['secret'])
    db.rollback()
    assert dispatch_tool(override.tool_key, channel='fixed', context=context, action='ok', secret=payload['secret']) == 'done'
    db.commit()
    with Session(bind=db.bind) as audit:
        rows = audit.query(RuntimeEventFact).filter_by(task_run_id=context.task_run_id, event_type='TOOL_CALL').order_by(RuntimeEventFact.id).all()
        assert [(row.status, row.error_code) for row in rows] == [
            ('REJECTED', 'TOOL_DISABLED'), ('REJECTED', 'TOOL_ATTEMPT_DEADLINE_EXCEEDED'),
            ('FAILED', 'ValueError'), ('SUCCEEDED', None),
        ]
        assert len({row.event_id for row in rows}) == 4
        for row in rows:
            assert row.attempt_id == attempt_id and row.task_id == context.task_id
            assert row.event_metadata['tool_call_id'] == row.event_id
            assert 'SYNTHETIC_SECRET_CONTENT' not in str(row.event_metadata)
        failure_event_id = rows[2].id
    finished = datetime.now()
    run.status, run.finished_at, run.error_code = 'FAILED', finished, 'CONTROLLED_TOOL_FAILURE'
    another_run = TaskRun(task_id=run.task_id, run_number=2, goal_snapshot='另一运行', status='SUCCEEDED')
    db.add(another_run)
    db.commit()
    scope = {'project_id': project, 'from_at': (finished - timedelta(days=1)).isoformat()}
    previous = api.get('/agent-governance/runtime/overview', username=admin, params={**scope, 'to_at': finished.isoformat()})
    assert previous.status_code == 200, previous.text
    assert previous.json()['summary']['failed_runs'] == 0 and previous.json()['recent_issues'] == []
    overview = api.get('/agent-governance/runtime/overview', username=admin,
                       params={**scope, 'to_at': (finished + timedelta(seconds=1)).isoformat()})
    assert overview.status_code == 200, overview.text
    data = overview.json()
    tool = next(row for row in data['tools'] if row['tool_key'] == override.tool_key)
    assert (tool['succeeded'], tool['failed'], tool['rejected']) == (1, 1, 2)
    assert data['summary']['traced_tool_success_rate'] == .5
    assert data['recent_issues'][0]['event']['id'] == failure_event_id
    focused = api.get(f'/task-runs/{run.id}/trace', username=admin, params={'event_id': failure_event_id})
    assert focused.status_code == 200, focused.text
    assert [item['id'] for item in focused.json()['items']] == [f'event:{failure_event_id}']
    assert api.get(f'/task-runs/{another_run.id}/trace', username=admin,
                   params={'event_id': failure_event_id}).status_code == 404
    old = finished - timedelta(days=12)
    another_run.status = 'RECONCILIATION_REQUIRED'
    another_run.created_at, another_run.updated_at = old, finished
    db.commit()
    historical = api.get('/agent-governance/runtime/overview', username=admin, params={
        'project_id': project, 'from_at': (old - timedelta(days=1)).isoformat(),
        'to_at': (old + timedelta(days=1)).isoformat(),
    }).json()
    assert historical['recent_issues'] == []
    current = api.get('/agent-governance/runtime/overview', username=admin,
                      params={**scope, 'to_at': (finished + timedelta(seconds=1)).isoformat()}).json()
    assert {item['run_id'] for item in current['recent_issues']} == {run.id, another_run.id}
