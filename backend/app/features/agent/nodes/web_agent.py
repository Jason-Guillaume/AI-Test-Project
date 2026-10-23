"""Web 智能体节点：observe→decide→act 循环 + 人工步骤 review（Phase 2，§二轮）。

节点职责：
- web_observe_node：调用 BrowserSession.observe() 取脱敏语义树与遮罩截图，写回 state。
- web_decide_node：调 LLM 结构化输出决策（PROPOSE / OBSERVE / DONE）。
- web_act_node：从进程级 SessionRegistry 取活句柄执行单步，写 web_agent_step 留痕。
- web_step_review_node：interrupt_before 暂停标记，人工在此 confirm / reject / promote。

安全不变量：
- LLM 只看**脱敏后的 accessibility tree** 与已遮罩截图元信息，从不接触原始 DOM。
- 沙箱探索**不走** run_web_case / confirmed_digest；授权来自会话打开时固定的
  TargetPolicy（DNS 冻结 + route 拦截 + 出站白名单）。
- 正式执行仍只走 save_case → confirm_case → debug，本节点组永不产出 TestRun。
- 双重循环守卫：web_step_budget 限制执行步数，web_observe_count 限制「只看不做」的
  空转轮次，避免 LLM 反复 OBSERVE 时无限循环。

DB 约定：本文件不直接 commit，行落库委托 WebUIService.record_agent_step。
"""

from __future__ import annotations

from typing import Any

from app.features.agent.nodes._context import NodeContext
from app.features.agent.nodes.validator import assert_no_forbidden_fields
from app.features.agent.providers.llm_provider import LLMError
from app.features.agent.prompts import load_prompt
from app.features.agent.schemas import WebDecideDraft
from app.features.agent.state import AgentState, set_error
from app.features.web_ui.schemas import WebStep
from app.features.web_ui.runtime.session_manager import registry

# 送入 prompt 的语义树上限（控制 token）
_TREE_MAX = 3000


def _browser_or_none(session_id: int | None):
    """取活会话句柄；缺失、已关闭或未登记均返回 None。"""
    if not session_id:
        return None
    return registry.get_session(session_id)


def _step_label(step: dict[str, Any]) -> str:
    """生成单步的短描述（用于消息历史与 prompt 里的「已执行步骤」）。"""
    locator = step.get("locator") or {}
    target = locator.get("value") or locator.get("strategy") or ""
    return f"{step.get('operation', '?')}({str(target)[:50]})"


def _budget_exhausted(state: AgentState) -> bool:
    """步数预算或空转轮次是否已耗尽（观测节点与条件边共用同一判定）。"""
    budget = state.get("web_step_budget") or 10
    executed = len(state.get("web_proposed_steps") or [])
    return executed >= budget or (state.get("web_observe_count") or 0) >= budget


def web_observe_node(ctx: NodeContext, state: AgentState) -> dict:
    """观测节点：取当前页面的脱敏语义树与遮罩截图，写回 state 供决策使用。

    首轮同时把用户自然语言目标固化到 web_goal（后续轮次由持久化重建，
    不依赖本轮请求参数）。预算耗尽时把阶段置为 WEB_STEP_REVIEW——因为
    interrupt_before 会在 web_step_review 之前停下，节点本身不会执行，
    阶段必须由**产出该暂停点**的节点设置（与 zap_scan_planner 同范式）。
    """
    if state.get("action") == "reject_web_step":
        try:
            from app.features.agent.services import session_service
            session_service.reject_web_proposal(ctx.db, state.get("session_id"))
        except Exception as exc:  # noqa: BLE001 — 拒绝失败时不能假装步骤已驳回
            ctx.db.rollback()
            return {
                **set_error(state, "WEB_STEP_MISSING", f"无法驳回待确认步骤（{type(exc).__name__}）"),
                "web_current_step": None,
            }

    browser = _browser_or_none(state.get("web_agent_session_id"))
    if browser is None:
        return {
            **set_error(state, "WEB_SESSION_CLOSED", "浏览器会话不存在或已断开，请重新启动会话"),
            "web_current_step": None,
        }

    try:
        observation = browser.observe()
    except Exception as exc:  # noqa: BLE001 — 浏览器层异常不穿透，转节点错误
        return {
            **set_error(state, "WEB_OBSERVE_FAILED", f"页面观测失败（{type(exc).__name__}），请检查浏览器会话后重试"),
            "web_current_step": None,
        }

    updates: dict[str, Any] = {
        # 观测到的是**当前真实页面**，跨入本节点的路径（驳回提案、用户改发新消息、
        # 执行后回环、LLM 决定继续观察）都不再针对旧页面上的那个提案，因此清掉待确认
        # 项。不清的话，一个已驳回 / 已失效的提案会一直留在 web_step_review 暂停点上，
        # 用户点「确认执行」就会把一个从未被重新确认过的步骤真的执行掉。
        "web_current_step": None,
        "web_current_observation": observation,
    }
    if state.get("action") == "reject_web_step":
        # 即使模型原样重提相同 JSON，也必须落一条新的待确认消息；旧提案已标为
        # REJECTED，单靠字段值比较无法检测这次「新提案」事件。
        updates["web_state_reset"] = True
    # 步数预算以活句柄为唯一事实源：每次观测刷新，跨轮次重建也不漂移。
    updates["web_step_budget"] = browser.step_budget
    # 自然语言消息代表新的探索目标；action 续轮没有 user_message 时沿用旧目标。
    goal = state.get("user_message") or state.get("web_goal")
    if goal:
        updates["web_goal"] = str(goal)[:500]
    if _budget_exhausted(state):
        updates["current_stage"] = "WEB_STEP_REVIEW"
    return updates


def web_decide_node(ctx: NodeContext, state: AgentState) -> dict:
    """决策节点：LLM 基于脱敏观测产出 WebDecideDraft（PROPOSE / OBSERVE / DONE）。

    流程：组装脱敏上下文 → generate_structured(kind="web_decide") → Pydantic 校验
    → 提案再经 WebStep 二次校验（定位器/操作白名单），无效提案直接报错不执行。
    """
    observation = state.get("web_current_observation") or {}
    budget = state.get("web_step_budget") or 10
    steps = state.get("web_proposed_steps") or []
    goal = state.get("web_goal") or state.get("user_message") or ""

    tree = (observation.get("accessibility_tree") or "")[:_TREE_MAX]
    history = "\n".join(
        f"{i}. {_step_label(step)}" for i, step in enumerate(steps[-5:], 1)
    ) or "（尚无已执行步骤）"

    user_content = (
        f"## 当前页面\n"
        f"URL: {observation.get('url', '')}\n"
        f"标题: {observation.get('title', '')}\n\n"
        f"## 页面语义树（已脱敏，不含原始 DOM）\n{tree}\n\n"
        f"## 已执行步骤\n{history}\n\n"
        f"## 用户目标\n{goal}\n\n"
        f"## 剩余步骤预算\n{max(budget - len(steps), 0)}"
    )

    try:
        result = ctx.provider.generate_structured(
            system=load_prompt("web_decide"),
            user_content=user_content,
            kind="web_decide",
        )
        # 与其他节点一致：LLM 夹带 script/sql/shell/payload 键即硬拒绝，不重试。
        assert_no_forbidden_fields(result)
        draft = WebDecideDraft.model_validate(result)
    except (LLMError, ValueError, Exception) as exc:  # noqa: BLE001
        return set_error(state, "STRUCTURED_OUTPUT_INVALID", f"Web 决策输出无效（{type(exc).__name__}），请重新发送目标")

    updates: dict[str, Any] = {"web_last_decision": draft.decision}

    if draft.decision == "OBSERVE":
        # 继续观察：不做操作，回到 observe。计数用于防止只看不做的空转循环。
        updates["web_current_step"] = None
        updates["web_observe_count"] = (state.get("web_observe_count") or 0) + 1
        return updates

    if draft.decision == "DONE":
        # 目标达成：循环结束。已接受的步骤可由 promote 提升为正式用例（Phase C）。
        updates["web_current_step"] = None
        updates["current_stage"] = "COMPLETED"
        return updates

    # PROPOSE：提案必须能通过 WebStep 校验，否则视为无效而非直接执行。
    # 不传 context={"resolved": True}：与一期草稿生成、load_steps 同一口径，
    # 敏感值必须是 ${data.auth_*} 一类变量引用，提升为正式用例时才能通过。
    step = draft.step or {}
    try:
        WebStep.model_validate(step)
    except Exception as exc:  # noqa: BLE001 — pydantic 校验失败抛 ValueError/ValidationError
        return set_error(state, "WEB_STEP_INVALID", f"LLM 提出的步骤不符合允许的操作或字段格式（{type(exc).__name__}）")

    if len(steps) >= budget:
        return set_error(state, "WEB_BUDGET_EXCEEDED", "步骤预算已耗尽，请提升现有步骤或重新开会话")

    updates["web_current_step"] = step
    updates["current_stage"] = "WEB_STEP_REVIEW"
    return updates


def web_act_node(ctx: NodeContext, state: AgentState) -> dict:
    """执行节点：人工确认后执行单步操作（不过 confirmed_digest，沙箱内执行）。

    执行结果同时写入 web_proposed_steps（AgentState 留痕）与 web_agent_step 表
    （已执行步骤加密落库，供 promote 提升为正式用例）；待确认提案保存在加密消息元数据中。
    """
    session_id = state.get("web_agent_session_id")
    if not session_id or not state.get("web_current_step"):
        return set_error(state, "WEB_STEP_MISSING", "缺少浏览器会话或待执行步骤")

    browser = _browser_or_none(session_id)
    if browser is None:
        return set_error(state, "WEB_SESSION_CLOSED", "浏览器会话已断开，请重新启动会话")
    if browser.step_count >= browser.step_budget:
        return set_error(state, "WEB_BUDGET_EXCEEDED", "步骤预算已耗尽，请提升现有步骤或重新开会话")

    try:
        from app.features.agent.services import session_service
        proposal = session_service.claim_web_proposal(ctx.db, state.get("session_id"))
    except Exception as exc:  # noqa: BLE001 — 领取失败时不执行未确认步骤
        ctx.db.rollback()
        return set_error(state, "WEB_STEP_MISSING", f"待确认步骤不可用（{type(exc).__name__}），请重新获取提案")
    if proposal is None:
        return set_error(state, "WEB_STEP_MISSING", "待确认步骤不存在或已处理，请重新获取提案")
    step = proposal["step"]

    try:
        result = browser.execute_step(step)
    except Exception as exc:  # noqa: BLE001 — 执行异常也要终结已领取步骤
        result = {
            "status": "ERROR",
            "error_code": "WEB_STEP_FAILED",
            "error_message": f"操作失败（{type(exc).__name__}）",
        }

    # BrowserResult 状态词表：PASSED / FAILED / ERROR（见 playwright_executor）
    passed = result.get("status") == "PASSED"
    status = "ACCEPTED" if passed else "FAILED"

    # 终结已领取提案并记录加密执行结果；任一步骤留痕失败都不能伪装成可提升。
    try:
        from app.features.web_ui.router import service as web_ui_service
        from app.features.agent.services import session_service

        session_service.finish_web_proposal(
            ctx.db, state.get("session_id"), proposal["message_id"], status=status,
        )
        web_ui_service.record_agent_step(
            ctx.db,
            session_id,
            sort=len(state.get("web_proposed_steps") or []) + 1,
            step=step,
            result=result,
            status=status,
            actor=ctx.user,
        )
    except Exception as exc:  # noqa: BLE001 — 执行已发生但状态无法落库，必须阻断后续提升
        ctx.db.rollback()
        return set_error(state, "WEB_STEP_FAILED", f"步骤已执行但留痕失败（{type(exc).__name__}），无法提升；请检查页面后重新开始")

    steps = list(state.get("web_proposed_steps") or []) + [{**step, "status": status, "result": result}]
    return {
        "web_proposed_steps": steps,
        "web_current_step": None,
        "current_stage": "UNDERSTANDING",
    }


def web_step_review_node(ctx: NodeContext, state: AgentState) -> dict:
    """步骤 review 暂停标记（interrupt_before，正常流程下不会被执行）。

    人工在此暂停点选择：
    - confirm_web_step：确认当前提案 → web_act 执行
    - reject_web_step：驳回 → web_observe 刷新页面，再由 web_decide 重新决策
    提升为正式 Web 用例由 Web Agent 专用 HTTP 端点完成。
    """
    return {}


# --------------------------------------------------------------------------- 条件边路由


def route_after_web_observe(ctx: NodeContext, state: AgentState) -> str:
    """观测之后：双守卫判定是否继续决策。

    步数预算或空转轮次耗尽时强制停在 web_step_review，交人工决定是否提升现有步骤。
    """
    if state.get("error"):
        return "end"
    if _budget_exhausted(state):
        return "web_step_review"
    return "web_decide"


def route_after_web_decide(ctx: NodeContext, state: AgentState) -> str:
    """决策之后：按 LLM 决策路由。

    - PROPOSE 且提案有效 → web_step_review（暂停点，等人工确认）
    - DONE → END
    - OBSERVE / 无效 → web_observe（继续观察）
    """
    if state.get("error"):
        return "end"
    decision = state.get("web_last_decision")
    if decision == "DONE":
        return "end"
    if decision == "PROPOSE" and state.get("web_current_step"):
        return "web_step_review"
    return "web_observe"


def route_after_web_act(ctx: NodeContext, state: AgentState) -> str:
    """执行之后：无条件回到 observe，形成 observe→decide→act 闭环。"""
    return "end" if state.get("error") else "web_observe"
