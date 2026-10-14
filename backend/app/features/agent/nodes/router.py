"""Router 入口节点与条件边路由逻辑。

router 是工作流入口：按**持久化的 current_stage** + **本次 action** 决定跳到哪一段，
从而**跳过已完成节点**——这是「无 checkpointer、每次请求全新 invoke」设计能正确续轮
的关键（§26/§15）。条件边函数由 graph.py 引用。

review 节点（test_point_review / test_case_review）是 `interrupt_before` 暂停标记：
invoke 到达它们之前会自动停下并返回当前 state，节点本身不执行任何逻辑。
"""

from __future__ import annotations

from app.features.agent.nodes._context import NodeContext
from app.features.agent.state import AgentState


def router_node(ctx: NodeContext, state: AgentState) -> dict:
    """入口节点：不修改状态，路由完全由后续条件边完成。"""
    return {}


def route_entry(ctx: NodeContext, state: AgentState) -> str:
    """router 之后的条件边：review 暂停点的快捷操作优先，否则走意图识别。

    快捷操作（action）对应前端按钮：
    - confirm_points：确认测试点 → 进入用例生成
    - confirm_cases：确认用例 → 推进到 READY_TO_EXECUTE（不执行）
    - execute：执行 → 进入执行
    - analyze：分析结果
    - regenerate_points / regenerate_cases：重新生成
    无 action（或 action=continue/query）= 新的自然语言消息，走 intent。
    """
    action = state.get("action")
    if action == "confirm_points":
        return "test_case_generator"
    if action == "confirm_cases":
        return "confirm_cases"
    if action == "execute":
        return "execution"
    if action == "analyze":
        return "result_analyzer"
    if action == "regenerate_points":
        return "test_point_generator"
    if action == "regenerate_cases":
        return "test_case_generator"
    return "intent"


def route_after_intent(ctx: NodeContext, state: AgentState) -> str:
    """intent 节点之后的条件边：按识别出的意图选择下一节点。

    - 生成类意图 → context_loader（开始生成链）
    - 执行已有用例 → test_case_review（暂停点，人工选用例 + 环境）
    - 分析结果 → result_analyzer（直接分析最近一次执行）
    - 查询资产 → query（只读查询后结束）
    - CLARIFY → END（澄清提问，不猜危险操作）
    """
    intent = state.get("intent")
    if intent in ("GENERATE_TEST_POINTS", "GENERATE_AND_EXECUTE"):
        return "context_loader"
    if intent == "EXECUTE_EXISTING_CASES":
        return "test_case_review"
    if intent == "ANALYZE_RESULT":
        return "result_analyzer"
    if intent == "QUERY_TEST_ASSET":
        return "query"
    return "clarify_end"


def confirm_cases_node(ctx: NodeContext, state: AgentState) -> dict:
    """确认测试用例：仅推进阶段到 READY_TO_EXECUTE，不执行。

    confirmed_case_ids 已在 run_agent 中写入 state（缺省全选）。
    用户后续通过 execute action 选择环境后才会触发实际执行。
    """
    return {"current_stage": "READY_TO_EXECUTE"}


def test_point_review_node(ctx: NodeContext, state: AgentState) -> dict:
    """测试点 review 暂停标记（interrupt_before，正常流程下不会被执行）。"""
    return {}


def test_case_review_node(ctx: NodeContext, state: AgentState) -> dict:
    """测试用例 review 暂停标记（interrupt_before，正常流程下不会被执行）。"""
    return {}
