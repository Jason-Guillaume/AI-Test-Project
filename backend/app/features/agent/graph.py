"""Agent 工作流图（langgraph StateGraph）+ 单次请求编排 run_agent。

**无 checkpointer 设计**（§26）：每次 HTTP 请求重建完整 AgentState 后做一次全新
`invoke`，由入口 `router` 节点按持久化的 `current_stage` + 入参 `action` 经条件边
跳到正确段（跳过已完成节点），跑到 `interrupt_before` 暂停点或 END 后持久化。
持久化完全在自建表（agent_session / agent_message），进程重启 / 浏览器刷新无损恢复
（§15）。

`interrupt_before=["test_point_review", "test_case_review", "report_review"]`：
langgraph 在执行到这三个 review 节点之前自动暂停本次 invoke 并返回当前 state，
实现 §14 human review 暂停点（report_review 用于人工确认是否推送飞书通知）。

错误守卫：每个可失败节点之后接条件边，`state.error` 存在时短路到 END（不再推进
后续节点），错误由 persist_turn 追加 SYSTEM 消息告知用户（§36）。
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph
from sqlalchemy.orm import Session

from app.features.agent.models.agent_message import AgentMessage
from app.features.agent.models.agent_session import AgentSession
from app.features.agent.nodes._context import NodeContext
from app.features.agent.nodes.context_loader import context_loader_node
from app.features.agent.nodes.execution import execution_node
from app.features.agent.nodes.intent import intent_node
from app.features.agent.nodes.query import query_node
from app.features.agent.nodes.notification_sender import notification_sender_node
from app.features.agent.nodes.report_generator import report_generator_node
from app.features.agent.nodes.report_review import report_review_node
from app.features.agent.nodes.result_analyzer import result_analyzer_node
from app.features.agent.nodes.security_context import security_context_loader_node
from app.features.agent.nodes.security_plan import (
    security_case_loader_node,
    security_case_materializer_node,
    security_plan_generator_node,
    security_plan_review_node,
    security_risk_confirm_node,
)
from app.features.agent.nodes.router import (
    confirm_cases_node,
    route_after_intent,
    route_entry,
    router_node,
    test_case_review_node,
    test_point_review_node,
)
from app.features.agent.nodes.save_asset import save_asset_node
from app.features.agent.nodes.test_case_generator import test_case_generator_node
from app.features.agent.nodes.test_point_generator import test_point_generator_node
from app.features.agent.nodes.test_planner import test_planner_node
from app.features.agent.nodes.validator import validator_node
from app.features.agent.providers.llm_provider import LLMProvider
from app.features.agent.providers.sanitizer import sanitize_text
from app.features.agent.schemas import AgentAction
from app.features.agent.services import session_service
from app.features.agent.state import AgentState
from app.models.identity import User


def _error_guard(ok_next: str):
    """条件边工厂：state 有 error 时短路到 END，否则路由到 ok_next。"""

    def route(ctx: NodeContext, state: AgentState) -> str:
        return "end" if state.get("error") else ok_next

    return route


def _clarify_guard(ok_next: str):
    """条件边工厂：error 或 CLARIFY 都短路到 END。

    安全上下文加载器遇到多目标时返回澄清而不置 error——它需要一条单独的出口，
    否则澄清会被继续路由到计划生成，变成「缺少安全上下文」的错误。
    """

    def route(ctx: NodeContext, state: AgentState) -> str:
        if state.get("error"):
            return "end"
        return "end" if state.get("current_stage") == "CLARIFY" else ok_next

    return route


def build_graph(ctx: NodeContext):
    """构造并编译 Agent 工作流图（每次 invoke 前重建，绑定本次 ctx）。"""
    graph = StateGraph(AgentState)

    graph.add_node("router", partial(router_node, ctx))
    graph.add_node("intent", partial(intent_node, ctx))
    graph.add_node("context_loader", partial(context_loader_node, ctx))
    graph.add_node("test_planner", partial(test_planner_node, ctx))
    graph.add_node("test_point_generator", partial(test_point_generator_node, ctx))
    graph.add_node("test_point_review", partial(test_point_review_node, ctx))
    graph.add_node("test_case_generator", partial(test_case_generator_node, ctx))
    graph.add_node("validator", partial(validator_node, ctx))
    graph.add_node("save_asset", partial(save_asset_node, ctx))
    graph.add_node("test_case_review", partial(test_case_review_node, ctx))
    graph.add_node("confirm_cases", partial(confirm_cases_node, ctx))
    graph.add_node("execution", partial(execution_node, ctx))
    graph.add_node("result_analyzer", partial(result_analyzer_node, ctx))
    graph.add_node("report_generator", partial(report_generator_node, ctx))
    graph.add_node("report_review", partial(report_review_node, ctx))
    graph.add_node("notification_sender", partial(notification_sender_node, ctx))
    graph.add_node("query", partial(query_node, ctx))
    # 安全测试链（Phase F，§13.2）：上下文 → 代码生成计划 →[暂停]计划 review
    graph.add_node("security_context_loader", partial(security_context_loader_node, ctx))
    graph.add_node("security_plan_generator", partial(security_plan_generator_node, ctx))
    graph.add_node("security_plan_review", partial(security_plan_review_node, ctx))
    graph.add_node("security_case_materializer", partial(security_case_materializer_node, ctx))
    graph.add_node("security_case_loader", partial(security_case_loader_node, ctx))
    graph.add_node("security_risk_confirm", partial(security_risk_confirm_node, ctx))

    graph.add_edge(START, "router")

    # 入口路由：action 优先（review 暂停点快捷操作），否则走意图识别。
    graph.add_conditional_edges("router", partial(route_entry, ctx), {
        "intent": "intent",
        "test_case_generator": "test_case_generator",
        "confirm_cases": "confirm_cases",
        "execution": "execution",
        "result_analyzer": "result_analyzer",
        "test_point_generator": "test_point_generator",
        "notification_sender": "notification_sender",
        "security_case_materializer": "security_case_materializer",
        "security_risk_confirm": "security_risk_confirm",
    })
    # 意图路由：按识别出的意图选择下一节点。
    graph.add_conditional_edges("intent", partial(route_after_intent, ctx), {
        "context_loader": "context_loader",
        "test_case_review": "test_case_review",
        "result_analyzer": "result_analyzer",
        "query": "query",
        "security_context_loader": "security_context_loader",
        "security_case_loader": "security_case_loader",
        "clarify_end": END,
    })

    # 生成链：上下文 → 计划 → 测试点 →[暂停]测试点 review
    graph.add_conditional_edges(
        "context_loader", partial(_error_guard("test_planner"), ctx),
        {"test_planner": "test_planner", "end": END},
    )
    graph.add_conditional_edges(
        "test_planner", partial(_error_guard("test_point_generator"), ctx),
        {"test_point_generator": "test_point_generator", "end": END},
    )
    graph.add_conditional_edges(
        "test_point_generator", partial(_error_guard("test_point_review"), ctx),
        {"test_point_review": "test_point_review", "end": END},
    )
    graph.add_edge("test_point_review", END)

    # 用例链：用例生成 → 校验 → 保存 →[暂停]用例 review
    graph.add_conditional_edges(
        "test_case_generator", partial(_error_guard("validator"), ctx),
        {"validator": "validator", "end": END},
    )
    graph.add_conditional_edges(
        "validator", partial(_error_guard("save_asset"), ctx),
        {"save_asset": "save_asset", "end": END},
    )
    graph.add_conditional_edges(
        "save_asset", partial(_error_guard("test_case_review"), ctx),
        {"test_case_review": "test_case_review", "end": END},
    )
    graph.add_edge("test_case_review", END)
    graph.add_edge("confirm_cases", END)

    # 安全测试链：计划由代码生成（LLM 只选目标与策略），review 前不落 TestCase；
    # 人工 confirm_security_plan 才落库，随后复用 test_case_review 暂停点。
    graph.add_conditional_edges(
        "security_context_loader", partial(_clarify_guard("security_plan_generator"), ctx),
        {"security_plan_generator": "security_plan_generator", "end": END},
    )
    graph.add_conditional_edges(
        "security_plan_generator", partial(_error_guard("security_plan_review"), ctx),
        {"security_plan_review": "security_plan_review", "end": END},
    )
    graph.add_edge("security_plan_review", END)
    graph.add_conditional_edges(
        "security_case_materializer", partial(_error_guard("test_case_review"), ctx),
        {"test_case_review": "test_case_review", "end": END},
    )
    graph.add_conditional_edges(
        "security_case_loader", partial(_error_guard("test_case_review"), ctx),
        {"test_case_review": "test_case_review", "end": END},
    )
    graph.add_edge("security_risk_confirm", END)

    # 执行链：执行 → 分析 → 报告生成 →[暂停]报告 review → 通知发送
    # （报告为执行后的正式产物，自动生成；是否推送飞书由人工在 report_review 确认）
    graph.add_conditional_edges(
        "execution", partial(_error_guard("result_analyzer"), ctx),
        {"result_analyzer": "result_analyzer", "end": END},
    )
    graph.add_conditional_edges(
        "result_analyzer", partial(_error_guard("report_generator"), ctx),
        {"report_generator": "report_generator", "end": END},
    )
    graph.add_conditional_edges(
        "report_generator", partial(_error_guard("report_review"), ctx),
        {"report_review": "report_review", "end": END},
    )
    graph.add_edge("report_review", END)
    graph.add_edge("notification_sender", END)
    graph.add_edge("query", END)

    return graph.compile(
        # security_plan_review：安全计划已生成但未确认，用例还没落库（Phase F，§13.2）。
        interrupt_before=[
            "test_point_review", "test_case_review", "report_review", "security_plan_review",
        ],
    )


# action 描述：写入消息历史，便于刷新恢复后用户看到操作记录。
_ACTION_LABELS: dict[str, str] = {
    "confirm_points": "确认测试点",
    "confirm_cases": "确认测试用例",
    "execute": "执行测试",
    "analyze": "分析结果",
    "regenerate_points": "重新生成测试点",
    "regenerate_cases": "重新生成测试用例",
    "confirm_report": "确认报告并发送飞书通知",
    "skip_notification": "跳过飞书通知",
    "confirm_security_plan": "确认安全计划",
    "confirm_security_risk": "确认高风险用例",
}


def _ids_of(items: list[dict[str, Any]] | None) -> list[int]:
    """从带 id 的资产列表提取 id 列表（供 confirm/execute 缺省全选）。"""
    return [it["id"] for it in (items or []) if it.get("id")]


def run_agent(
    db: Session,
    session: AgentSession,
    user: User,
    provider: LLMProvider,
    *,
    content: str | None = None,
    action: AgentAction | None = None,
    point_ids: list[int] | None = None,
    case_ids: list[int] | None = None,
    environment_id: int | None = None,
    channel_id: int | None = None,
    security_item_indexes: list[int] | None = None,
    security_case_ids: list[int] | None = None,
) -> tuple[AgentState, list[AgentMessage]]:
    """单次请求编排：重建 state → 注入输入 → invoke → 持久化 → 返回。

    返回 (final_state, emitted_messages)。final_state 供路由层序列化 AgentTurnResponse；
    emitted_messages 是本轮新增的 ASSISTANT/SYSTEM 消息。
    """
    initial: AgentState = session_service.load_state(db, session)

    if content:
        initial["user_message"] = sanitize_text(content)
        session_service.append_message(
            db, session.id, role="USER", message_type="TEXT", content=content,
        )

    if action:
        initial["action"] = action
        initial["action_payload"] = {
            "point_ids": point_ids,
            "case_ids": case_ids,
            "environment_id": environment_id,
            "channel_id": channel_id,
            # Phase F：安全计划确认（预览项 index）与高风险确认（TestCase id）。
            "security_item_indexes": security_item_indexes,
            "security_case_ids": security_case_ids,
        }
        session_service.append_message(
            db, session.id, role="USER", message_type="TEXT",
            content=_ACTION_LABELS.get(action, action),
        )
        # confirm / execute 的选中集合直接写入 state（缺省 = 全选已生成资产）。
        if action == "confirm_points":
            initial["confirmed_point_ids"] = point_ids or _ids_of(initial.get("generated_test_points"))
        if action in ("confirm_cases", "execute"):
            initial["confirmed_case_ids"] = case_ids or _ids_of(initial.get("generated_test_cases"))
            if environment_id:
                initial["environment_id"] = environment_id

    ctx = NodeContext(db=db, user=user, provider=provider)
    graph = build_graph(ctx)
    try:
        final: AgentState = graph.invoke(initial)  # 跑到 interrupt_before 或 END 返回
    except Exception as exc:  # noqa: BLE001 — langgraph 框架级异常兜底
        final = {**initial, "current_stage": "FAILED", "error": {"code": "INTERNAL_ERROR", "message": f"Agent 处理异常：{exc}"}}
    emitted = session_service.persist_turn(db, session, initial=initial, final=final)
    return final, emitted
