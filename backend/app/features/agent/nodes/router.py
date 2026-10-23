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
    - confirm_security_plan：确认安全计划 → 把预览项落成安全用例（人工按钮）
    - confirm_security_risk：高风险用例人工确认（人工按钮，执行前必需）
    - confirm_security_scan：确认 ZAP 扫描计划 → 创建扫描任务（人工按钮，唯一入口）
    - confirm_report / skip_notification：报告 review 暂停点的两个出口（确认推送飞书
      或跳过通知，报告本身已落库）
    - confirm_web_step：确认 Web 智能体的步骤提案 → web_act 执行
    - reject_web_step：驳回提案 → web_observe 重新取真实页面（清掉待确认项）
      两者是 web_step_review 暂停点的两个出口
    提升为正式 Web 用例通过 Web Agent 专用 HTTP 端点完成，不作为 Agent action 暴露。
    无 action（或 action=continue/query）= 新的自然语言消息，走 intent。
    """
    action = state.get("action")
    if action in ("confirm_report", "skip_notification"):
        return "notification_sender"
    if action == "confirm_points":
        return "test_case_generator"
    if action == "confirm_cases":
        return "confirm_cases"
    if action == "confirm_security_plan":
        # 只由人工按钮触发：把 PlanService.preview 的预览项落成安全用例。
        return "security_case_materializer"
    if action == "confirm_security_risk":
        # 同样只由人工触发；LLM 工具里没有这个参数（§13.2）。
        return "security_risk_confirm"
    if action == "confirm_security_scan":
        # 唯一能创建 ZAP 扫描任务的路径（§二十三）：LLM 工具里没有这个 action，
        # 因此这里进入的每一次调用都对应一次真实的人类点击。
        return "zap_scan_job_creator"
    if action == "confirm_web_step":
        # 人工确认 Web 智能体的步骤提案后才执行（沙箱内，仍不落 TestRun）。
        return "web_act"
    if action == "reject_web_step":
        # 驳回当前提案：回到观测节点取一次**真实页面**，而不是复用落库时截断到 2000
        # 字符的旧语义树——驳回往往发生在页面已变化之后，用旧树决策等于让 LLM 猜。
        return "web_observe"
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
    - 生成用例（已有测试点） → test_case_generator（跳过 context_loader，复用已确认点）
    - 执行已有用例 → test_case_review（暂停点，人工选用例 + 环境）
    - 分析结果 → result_analyzer（直接分析最近一次执行）
    - 查询资产 → query（只读查询后结束）
    - 安全测试生成 → security_context_loader（计划由代码生成，LLM 只选目标与策略）
    - 执行安全测试 → security_case_loader（只列 case_type='SECURITY'，再停 test_case_review）
    - 分析安全结果 → result_analyzer；查询 Finding → query（只读摘要，不含 evidence）
    - 发起 ZAP 扫描 → zap_scan_planner（只出计划，停在人工确认，不创建任务）
    - 交互式 Web 用例编写 → web_observe（先取一次真实页面观测，再进循环）
    - CLARIFY → END（澄清提问，不猜危险操作）
    """
    intent = state.get("intent")
    if intent == "INTERACTIVE_WEB_AUTHORING":
        return "web_observe"
    if intent in ("GENERATE_TEST_POINTS", "GENERATE_AND_EXECUTE"):
        return "context_loader"
    if intent == "GENERATE_TEST_CASES":
        return "test_case_generator"
    if intent == "EXECUTE_EXISTING_CASES":
        return "test_case_review"
    if intent == "GENERATE_SECURITY_TEST":
        return "security_context_loader"
    if intent == "EXECUTE_SECURITY_TEST":
        return "security_case_loader"
    if intent == "REQUEST_SECURITY_SCAN":
        return "zap_scan_planner"
    if intent in ("ANALYZE_RESULT", "ANALYZE_SECURITY_RESULT"):
        return "result_analyzer"
    if intent in ("QUERY_TEST_ASSET", "QUERY_SECURITY_FINDING"):
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
