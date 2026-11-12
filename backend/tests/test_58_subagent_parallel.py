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
