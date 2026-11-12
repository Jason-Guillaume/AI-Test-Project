"""上下文选择按 Agent 会话隔离，并遵守 Token 预算与来源追溯。"""

from datetime import datetime
from types import SimpleNamespace

from app.agents.services.context_manager import assemble_history


def test_relevant_history_is_selected_with_source_manifest():
    """当前查询可召回相关旧消息，清单保留引用与会话权限范围。"""
    session = SimpleNamespace(id=12, project_id=4, task_agent_instance_id=31)
    messages = [
        SimpleNamespace(id=1, role="USER", message_type="TEXT", content="支付流程需要支持退款", created_at=datetime.now()),
        SimpleNamespace(id=2, role="ASSISTANT", message_type="TEXT", content="今天先看首页布局", created_at=datetime.now()),
        SimpleNamespace(id=3, role="USER", message_type="TEXT", content="请继续", created_at=datetime.now()),
    ]
    selected, manifest = assemble_history(
        session=session, messages=messages, query="支付退款", token_budget=40, max_messages=2,
    )
    assert [message["content"] for message in selected] == ["支付流程需要支持退款", "请继续"]
    assert manifest["permission_scope"] == {
        "project_id": 4, "agent_session_id": 12, "agent_run_id": 31,
    }
    assert [item["id"] for item in manifest["source_refs"]] == [1, 3]
    assert manifest["estimated_tokens"] <= manifest["token_budget"]
    assert manifest["omitted_message_count"] == 1


def test_latest_message_is_retained_and_clipped_to_budget():
    """预算不足时保留最新目标尾部，并把估算 token 控制在预算内。"""
    session = SimpleNamespace(id=7, project_id=2, task_agent_instance_id=9)
    messages = [
        SimpleNamespace(id=1, role="USER", message_type="TEXT", content="支付退款规则" * 20, created_at=datetime.now()),
        SimpleNamespace(id=2, role="USER", message_type="TEXT", content="历史内容" * 30 + "订单号12345", created_at=datetime.now()),
    ]
    selected, manifest = assemble_history(
        session=session, messages=messages, query="支付退款", token_budget=12, max_messages=8,
    )

    assert selected
    assert selected[-1]["content"].endswith("12345")
    assert manifest["source_refs"][-1]["id"] == 2
    assert manifest["truncated_message_ids"] == [2]
    assert manifest["estimated_tokens"] <= 12


def test_manifest_counts_messages_outside_bounded_candidate_window():
    """分页读取后清单仍区分已装配、候选窗口和未搜索的历史消息。"""
    session = SimpleNamespace(id=5, project_id=2, task_agent_instance_id=9)
    messages = [
        SimpleNamespace(id=99, role="USER", message_type="TEXT", content="当前问题", created_at=None),
        SimpleNamespace(id=100, role="ASSISTANT", message_type="TEXT", content="回答", created_at=None),
    ]
    selected, manifest = assemble_history(
        session=session, messages=messages, query="当前", token_budget=100,
        max_messages=8, total_message_count=100,
    )

    assert selected[-1]["content"] == "回答"
    assert manifest["candidate_message_count"] == 2
    assert manifest["unsearched_message_count"] == 98
    assert manifest["omitted_message_count"] == 98


def test_current_user_question_is_preserved_ahead_of_later_assistant_history():
    session = SimpleNamespace(id=6, project_id=2, task_agent_instance_id=9)
    messages = [
        SimpleNamespace(id=1, role="USER", message_type="TEXT", content="当前要处理退款", created_at=None),
        SimpleNamespace(id=2, role="ASSISTANT", message_type="TEXT", content="较新的旧回答", created_at=None),
    ]
    selected, _ = assemble_history(
        session=session, messages=messages, query="当前要处理退款",
        token_budget=100, max_messages=1,
    )
    assert selected == [{"role": "user", "content": "当前要处理退款"}]


def test_long_term_memory_is_explicitly_scoped_in_context_manifest():
    session = SimpleNamespace(id=6, project_id=2, task_agent_instance_id=9)
    messages = [
        SimpleNamespace(id=3, role="USER", message_type="TEXT", content="请处理退款", created_at=None),
    ]
    memories = [{
        "id": 15, "memory_key": "refund-policy", "version": 2,
        "content": "退款使用原支付渠道", "source_digest": "a" * 64,
        "source_refs": [{"kind": "USER_PROVIDED", "created_by": 1}],
    }]
    selected, manifest = assemble_history(
        session=session, messages=messages, query="退款", token_budget=300,
        max_messages=8, long_term_memories=memories,
    )
    assert selected[0]["content"].startswith("以下是同一项目、同一 Agent")
    assert "退款使用原支付渠道" in selected[0]["content"]
    assert manifest["memory_count"] == 1
    assert manifest["memory_ids"] == [15]
    assert manifest["estimated_tokens"] <= 300
