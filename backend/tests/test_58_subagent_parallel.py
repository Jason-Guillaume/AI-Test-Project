"""通用任务中的叶子子 Agent 以有界 LangGraph fan-out/fan-in 并行运行。"""

from contextlib import contextmanager
from threading import Barrier, Lock

import app.agents.runtime.subagents as subagents


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
