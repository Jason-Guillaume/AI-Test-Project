"""Agent 工作流状态（AgentState）+ 阶段/错误辅助。

用 langgraph TypedDict 定义状态：节点返回部分 dict，langgraph 按「覆盖」语义合并
（列表字段整体覆盖，不做累加）。这与「每次请求从 DB 重建完整 state 后全新 invoke」
的设计一致——节点只产出当前段的结果，完整状态始终以 agent_session/agent_message
为单一事实源（§26）。

不在本文件做 DB 读写：load/persist 放在 services/session_service.py。
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.features.agent.schemas import AGENT_STAGES


class AgentState(TypedDict, total=False):
    """langgraph 工作流状态。

    total=False：允许 invoke 时缺省部分键（router 按存在的键 + current_stage 路由）。
    """

    # --- 会话与本次请求上下文 ---
    session_id: int | None
    project_id: int
    user_id: int | None
    user_message: str | None  # 本次用户自然语言输入
    action: str | None  # 本次 review 暂停点的快捷操作（confirm_points/execute/...）
    action_payload: dict[str, Any]  # point_ids/case_ids/environment_id 等本次附带参数

    # --- 意图与目标 ---
    intent: str | None
    target_type: str | None  # API / BUSINESS_FLOW / BUSINESS_ACTION
    target_ids: list[int]

    # --- ContextLoader 产出的最小上下文（已脱敏）---
    api_context: dict[str, Any] | None
    business_context: dict[str, Any] | None
    strategy_context: list[dict[str, Any]]
    existing_test_context: dict[str, Any] | None

    # --- 规划 / 生成产物 ---
    test_plan: dict[str, Any] | None
    generated_test_points: list[dict[str, Any]]
    generated_test_cases: list[dict[str, Any]]
    confirmed_point_ids: list[int]
    confirmed_case_ids: list[int]
    environment_id: int | None  # 执行环境（execute 时由人工确认）
    clarify_question: str | None  # intent=CLARIFY 时的澄清提问（不落库，仅本轮用）
    generation_version: int  # 本轮生成版本号（= 历史生成次数 + 1，写入资产追溯）

    # --- 校验 / 执行 / 分析 ---
    validation_errors: list[dict[str, Any]]
    test_run_id: int | None
    execution_result: dict[str, Any] | None
    analysis: dict[str, Any] | None

    # --- 报告闭环 + 飞书通知（Phase 2，§二四）---
    report_id: int | None
    report_brief: dict[str, Any] | None  # 脱敏报告摘要（report_no/风险/通过率/AI 总结）
    notification_record_id: int | None  # 最近一次飞书发送记录ID
    notification_brief: dict[str, Any] | None  # 通知结果（status/error_message/skipped/channel_name）

    # --- 控制 ---
    current_stage: str
    error: dict[str, Any] | None  # {"code": ..., "message": ...}
    messages: list[dict[str, Any]]  # 供 prompt 的消息历史（脱敏，截断）


def make_initial_state(project_id: int, user_id: int | None, session_id: int | None = None) -> AgentState:
    """构造一个全字段初始化的空状态（invoke 入口用）。"""
    return AgentState(
        session_id=session_id,
        project_id=project_id,
        user_id=user_id,
        user_message=None,
        action=None,
        action_payload={},
        intent=None,
        target_type=None,
        target_ids=[],
        api_context=None,
        business_context=None,
        strategy_context=[],
        existing_test_context=None,
        test_plan=None,
        generated_test_points=[],
        generated_test_cases=[],
        confirmed_point_ids=[],
        confirmed_case_ids=[],
        environment_id=None,
        clarify_question=None,
        generation_version=1,
        validation_errors=[],
        test_run_id=None,
        execution_result=None,
        analysis=None,
        report_id=None,
        report_brief=None,
        notification_record_id=None,
        notification_brief=None,
        current_stage="UNDERSTANDING",
        error=None,
        messages=[],
    )


def set_error(state: AgentState, code: str, message: str, stage: str = "FAILED") -> dict[str, Any]:
    """返回一个把 state 标记为失败的部分更新（节点 except 分支用）。

    返回部分 dict（而非就地改 state），符合 langgraph「节点返回更新」语义。
    """
    return {
        "current_stage": stage,
        "error": {"code": code, "message": message},
    }


def is_terminal(stage: str) -> bool:
    """阶段是否为终态（COMPLETED/FAILED）。"""
    return stage in ("COMPLETED", "FAILED")


def is_review_stage(stage: str) -> bool:
    """阶段是否为 human review 暂停点（需人工确认才推进）。

    REPORT_REVIEW：报告已落库，人工确认后才触发飞书通知（不自动推送）。
    """
    return stage in ("TEST_POINT_REVIEW", "TEST_CASE_REVIEW", "READY_TO_EXECUTE", "REPORT_REVIEW")


# 合法阶段集合（供校验）。
VALID_STAGES = set(AGENT_STAGES)
