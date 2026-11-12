"""ZAP 安全扫描节点组（Phase 2，§二十三）。

三个节点串成「计划 → 人工确认 → 创建任务」的最小闭环，与 Phase F 的
security_plan_* 同构：

- `zap_scan_planner_node`：解析目标 / 策略 → 调 `job_service.plan` 出**计划预览**，
  纯读取，不写库、不发任何 ZAP 请求，然后停在 ZAP_SCAN_REVIEW；
- `zap_scan_review_node`：`interrupt_before` 暂停标记，本身不执行任何逻辑；
- `zap_scan_job_creator_node`：**唯一能创建扫描任务的路径**，只由人工
  `confirm_security_scan` action 触发。

**为什么 LLM 不能创建任务（§二十三「不能仅凭 LLM 输出 confirmed=true 就执行」）**：

`job_service.create` 的 `confirmed` 是普通布尔字段，LLM 只要幻觉出一个
`confirmed=true` 加一句编造的 approval_note 就能满足。因此这里把「确认」从
一个可被 LLM 伪造的参数，改成一次**只能由人类触发的图路由事件**：

1. LLM 侧（`zap_scan_tool`）没有创建任务的工具，`preview_scan` 恒传
   `confirmed=False`；
2. `router.route_entry` 只在 `action == "confirm_security_scan"` 时进入
   `zap_scan_job_creator`，而 LLM 的工具参数里没有这个 action；
3. 本节点仍断言 `state["action"]`，并把结果传给工具的 `human_approved`——
   两道独立闸门都过不了就不能建任务；
4. 即使前面全被绕过，`job_service.create` 仍独立校验权限 / 环境 / 目标授权 /
   确认 / 批准说明五关。

`approval_note` 只从 `action_payload`（人工在确认弹窗里填的）读取，**绝不**从
LLM 可写的 state 取——否则等于让 LLM 给自己写批准理由。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.agents.workflows.legacy.nodes._context import NodeContext
from app.agents.workflows.legacy.state import AgentState, set_error
from app.tools.builtin import zap_scan_tool
from app.core.http.errors import AppError

#: 人工确认动作的唯一字面量：LLM 的工具参数里没有它，因此本节点入口 = 人工点击。
CONFIRM_ACTION = "confirm_security_scan"

#: 目标 / 策略选择器需要的字段（不含范围与令牌类配置，避免诱导 LLM 去"优化"范围）。
_TARGET_FIELDS = (
    "id", "name", "target_type", "base_url", "enabled",
    "authorization_status", "active_scan_allowed", "is_production",
)
_PROFILE_FIELDS = (
    "id", "name", "scan_mode", "is_active_scan", "enabled",
    "max_duration", "max_depth", "max_concurrency",
)


def _pick(obj: dict, fields: tuple[str, ...]) -> dict[str, Any]:
    """选取对应数据。"""
    return {field: obj.get(field) for field in fields}


def _positive(values: list[Any] | None) -> list[int]:
    """校验正数对应数据。"""
    return [int(v) for v in (values or []) if isinstance(v, (int, str)) and str(v).isdigit()]


def _clarify(question: str) -> dict:
    """多目标时的澄清出口：不猜扫描范围（§35）。"""
    return {
        "intent": "CLARIFY",
        "clarify_question": question,
        "current_stage": "CLARIFY",
    }


def zap_scan_planner_node(ctx: NodeContext, state: AgentState) -> dict:
    """生成 ZAP 扫描计划预览并停在人工确认（不创建任务）。"""
    project_id = state["project_id"]
    payload = state.get("action_payload") or {}

    try:
        targets = zap_scan_tool.list_scan_targets(ctx.db, project_id, ctx.user)
        profiles = zap_scan_tool.list_scan_profiles(ctx.db, project_id, ctx.user)
    except HTTPException as exc:
        code = "TARGET_NOT_FOUND" if exc.status_code == 404 else "SECURITY_SCAN_PLAN_FAILED"
        return set_error(state, code, str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "SECURITY_SCAN_PLAN_FAILED", f"加载扫描目标失败：{exc}")

    if not targets or not profiles:
        missing = "扫描目标" if not targets else "扫描策略"
        return set_error(
            state, "SECURITY_SCAN_PLAN_FAILED",
            f"本项目没有可用的{missing}，请先在项目设置里配置",
        )

    enabled_targets = [t for t in targets if t.get("enabled")]
    enabled_profiles = [p for p in profiles if p.get("enabled")]
    if not enabled_targets or not enabled_profiles:
        missing = "启用的扫描目标" if not enabled_targets else "启用的扫描策略"
        return set_error(
            state, "SECURITY_SCAN_PLAN_FAILED",
            f"本项目没有{missing}，请先启用后再试",
        )

    # 目标 / 策略由人工在前端下拉框里指定（action_payload），或用项目内唯一的一个。
    # 刻意不交给 LLM 从自然语言里挑：那会变成「Agent 自动扩大扫描范围」。
    target_id = _positive([payload.get("zap_scan_target_id")])[0] if payload.get("zap_scan_target_id") else None
    profile_id = _positive([payload.get("zap_scan_profile_id")])[0] if payload.get("zap_scan_profile_id") else None

    if target_id is None:
        if len(enabled_targets) != 1:
            names = "、".join(f"{t.get('name')}({t.get('id')})" for t in enabled_targets[:8])
            return _clarify(
                f"本项目有 {len(enabled_targets)} 个启用的扫描目标（{names}），"
                "请指定要扫描的目标后再发起"
            )
        target_id = int(enabled_targets[0]["id"])
    if profile_id is None:
        if len(enabled_profiles) != 1:
            names = "、".join(
                f"{p.get('name')}({p.get('id')})" for p in enabled_profiles[:8]
            )
            return _clarify(
                f"本项目有 {len(enabled_profiles)} 个启用的扫描策略（{names}），"
                "请指定要使用的策略后再发起"
            )
        profile_id = int(enabled_profiles[0]["id"])

    try:
        plan = zap_scan_tool.preview_scan(
            ctx.db, project_id, ctx.user,
            target_id=target_id, scan_profile_id=profile_id,
        )
    except HTTPException as exc:
        return set_error(state, _code_of(exc), f"扫描计划生成失败：{exc.detail}")
    except AppError as exc:
        return set_error(state, _code_of(exc), str(exc))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "SECURITY_SCAN_PLAN_FAILED", f"扫描计划生成失败：{exc}")

    plan_view = {
        **plan,
        "target_id": target_id,
        "scan_profile_id": profile_id,
        "choices": {
            "targets": [_pick(t, _TARGET_FIELDS) for t in enabled_targets],
            "profiles": [_pick(p, _PROFILE_FIELDS) for p in enabled_profiles],
        },
    }
    note = "确认后才创建任务"
    if plan.get("is_active_scan"):
        note = "主动扫描：确认时请一并填写批准说明"
    return {
        "zap_scan_plan": plan_view,
        "current_stage": "ZAP_SCAN_REVIEW",
        "zap_scan_job_id": None,
        "zap_scan_note": note,
    }


def zap_scan_review_node(ctx: NodeContext, state: AgentState) -> dict:
    """ZAP 扫描计划 review 暂停标记（interrupt_before，正常流程下不会被执行）。"""
    return {}


def _code_of(exc: BaseException) -> str:
    """把 service 层错误映射到 Agent 错误码（403=授权不足，404=目标不可用）。"""
    status = getattr(exc, "status_code", None)
    code = getattr(exc, "code", None)
    if status == 403 or status == 401:
        return "SECURITY_SCAN_NOT_AUTHORIZED"
    if status == 404:
        return "TARGET_NOT_FOUND"
    return str(code) if code else "SECURITY_SCAN_PLAN_FAILED"


def zap_scan_job_creator_node(ctx: NodeContext, state: AgentState) -> dict:
    """人工确认扫描计划后创建扫描任务（`confirm_security_scan` action 专用）。

    本节点由 `route_entry` 的 action 分支进入，LLM 工具里没有这个 action，
    所以每次到达这里都对应一次真实的人类确认。节点内仍再断言一次 action，
    并把结论传给工具的 `human_approved`——两道闸门互相独立。
    """
    project_id = state["project_id"]
    human_confirmed = state.get("action") == CONFIRM_ACTION
    payload = state.get("action_payload") or {}

    reviewed = state.get("zap_scan_plan") or {}
    target_id = reviewed.get("target_id")
    profile_id = reviewed.get("scan_profile_id")
    if target_id is None or profile_id is None:
        return set_error(
            state, "SECURITY_SCAN_PLAN_FAILED",
            "没有待确认的扫描计划（请先生成扫描计划）",
        )
    if state.get("zap_scan_job_id"):
        return set_error(
            state, "SECURITY_SCAN_PLAN_FAILED",
            f"任务 #{state['zap_scan_job_id']} 已由本会话创建，请勿重复确认",
        )

    # 批准说明必须来自人工在确认弹窗里的输入；LLM 可写的 state 一律不作为来源。
    approval_note = (payload.get("approval_note") or "").strip()

    # 复核强度是否变了：人在预览的是被动计划，此刻却已是主动扫描，
    # 说明期间有人改了策略——不能用一次被动确认去放行主动扫描。
    try:
        fresh = zap_scan_tool.preview_scan(
            ctx.db, project_id, ctx.user,
            target_id=int(target_id), scan_profile_id=int(profile_id),
        )
    except HTTPException as exc:
        return set_error(state, _code_of(exc), f"确认前复核扫描计划失败：{exc.detail}")
    except AppError as exc:
        return set_error(state, _code_of(exc), str(exc))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "SECURITY_SCAN_PLAN_FAILED", f"确认前复核扫描计划失败：{exc}")

    if fresh.get("is_active_scan") and not reviewed.get("is_active_scan"):
        return set_error(
            state, "SECURITY_SCAN_NOT_AUTHORIZED",
            "该策略在确认前被调整为主动扫描，需要针对主动扫描重新生成计划并批准",
        )

    if fresh.get("zap_available") is False:
        return set_error(
            state, "SECURITY_SCAN_PLAN_FAILED",
            "ZAP 服务当前不可用，任务无法执行；请先确认部署侧 ZAP 配置",
        )

    try:
        job = zap_scan_tool.create_scan_job(
            ctx.db, project_id, ctx.user,
            target_id=int(target_id), scan_profile_id=int(profile_id),
            human_approved=human_confirmed,
            approval_note=approval_note or None,
        )
    except ValueError as exc:
        # 工具层闸门被触发（理论上到不了这里：action 已断言）。
        return set_error(state, "SECURITY_SCAN_NOT_AUTHORIZED", str(exc))
    except HTTPException as exc:
        code = _code_of(exc)
        if fresh.get("is_active_scan") and exc.status_code == 403 and not approval_note:
            code = "SECURITY_SCAN_NOT_AUTHORIZED"
        return set_error(state, code, f"扫描任务创建失败：{exc.detail}")
    except AppError as exc:
        return set_error(state, _code_of(exc), f"扫描任务创建失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "SECURITY_SCAN_PLAN_FAILED", f"扫描任务创建失败：{exc}")

    job_id = int(job.get("id"))
    return {
        "zap_scan_job_id": job_id,
        "zap_scan_plan": {**reviewed, "confirmed": True, "job_id": job_id},
        "current_stage": "COMPLETED",
        "zap_scan_note": (
            f"扫描任务 #{job_id} 已创建（{'主动' if fresh.get('is_active_scan') else '被动'}扫描）"
            + (f"，批准说明：{approval_note[:60]}" if approval_note else "")
        ),
    }


__all__ = [
    "CONFIRM_ACTION",
    "zap_scan_planner_node",
    "zap_scan_review_node",
    "zap_scan_job_creator_node",
]
