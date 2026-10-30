"""按任务 Agent 配置动态构造的受控 LangGraph 子 Agent 节点。"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph

from app.core.security.sanitizer import sanitize_text


class _SubAgentState(TypedDict):
    """子图输入与按配置顺序收集的分析摘要。"""

    prompt: str
    insights: Annotated[list[dict[str, Any]], operator.add]


def run_subagent_graph(
    children: list[dict[str, Any]],
    prompt: str,
    provider_factory: Callable[[dict[str, Any]], Any],
    status_callback: Callable[[dict[str, Any], str], None] | None = None,
) -> list[dict[str, Any]]:
    """将任务快照中的叶子 Agent 定义逐个组装为 LangGraph 节点并运行。"""
    if not children:
        return []
    graph = StateGraph(_SubAgentState)
    node_names: list[str] = []
    for index, child in enumerate(children):
        node_name = f"child_agent_{index}"
        node_names.append(node_name)

        def run_child(state: _SubAgentState, *, child_snapshot: dict[str, Any] = child) -> dict[str, Any]:
            """以独立职责调用子 Agent；其输出只作为 Planner 的非权威建议。"""
            if status_callback is not None:
                status_callback(child_snapshot, "RUNNING")
            sections = [
                "你是任务中的子 Agent，只负责分析输入并给 Planner 提供简洁建议。",
                "你没有执行、写入、审批或扩大资源范围的权限；不得声称已完成任何操作。",
            ]
            instruction = str(child_snapshot.get("instruction") or "").strip()
            if instruction:
                sections.append(f"管理员配置的分析职责：\n{instruction}")
            for skill in child_snapshot.get("skills") or []:
                content = str(skill.get("content") or "").strip()
                if content:
                    sections.append(f"参考 Skill「{skill.get('name') or skill.get('key') or 'Skill'}」：\n{content}")
            sections.append("只输出不超过 1500 字的事实性分析，区分输入事实与推断。")
            try:
                result = provider_factory(child_snapshot).chat("\n\n".join(sections), state["prompt"])
            except Exception:
                if status_callback is not None:
                    status_callback(child_snapshot, "FAILED")
                raise
            if status_callback is not None:
                status_callback(child_snapshot, "SUCCEEDED")
            summary = sanitize_text(str(result or "").strip())[:6000]
            return {"insights": [{
                "name": str(child_snapshot.get("name") or "子 Agent")[:120],
                "version": int(child_snapshot.get("version") or 1),
                "summary": summary,
            }]}

        graph.add_node(node_name, run_child)
    graph.add_edge(START, node_names[0])
    for current, following in zip(node_names, node_names[1:]):
        graph.add_edge(current, following)
    graph.add_edge(node_names[-1], END)
    result = graph.compile().invoke({"prompt": prompt, "insights": []})
    return result.get("insights", [])
