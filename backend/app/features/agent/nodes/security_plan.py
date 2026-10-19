"""安全计划节点组（Phase F，§13.2）。

三个节点串成「计划 → 人工确认 → 落用例」的最小闭环：

- `security_plan_generator_node`：调 `PlanService.preview` 用**代码**展开变异清单
  （LLM 只选目标与策略，不生成任何变异体），写一条 DRAFT 计划但**不落 TestCase**；
- `security_plan_review_node`：`interrupt_before` 暂停标记，本身不执行任何逻辑；
- `security_case_materializer_node`：只由人工 `confirm_security_plan` action 触发，
  调 `PlanService.confirm` 把选中预览项写成 `case_type='SECURITY'` 用例；
- `security_risk_confirm_node`：只由人工 `confirm_security_risk` action 触发的
  高风险确认（§13.2「该 action 只在路由层接受，不进 LLM 工具参数」），
  执行节点永远不会自动补确认。

用例在 materializer 里 `confirmation_required=true` 且 `confirmed_at` 为空时保持
enabled：runner 执行时会跳过未确认项并说明原因，风险由人而不是代码承担。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.features.agent.nodes._context import NodeContext
from app.features.agent.state import AgentState, set_error
from app.features.agent.tools import security_tool, test_asset_tool
from app.features.security_testing.services.case_service import SecurityCaseService
from app.shared.errors import AppError

_CASE_SERVICE = SecurityCaseService()

#: 预览项里要带给前端 / 用户确认的字段（index 决定确认哪几条）。
_PLAN_ITEM_FIELDS = (
    "index", "name", "mutation_type", "target_type", "api_id", "business_action_id",
    "method", "location", "field", "expectation", "expected_status_codes",
    "severity", "risk_level", "confirmation_required", "blocked_reason",
    "source_rule_id", "source_strategy_id",
)


def _pick(obj: dict, fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: obj.get(field) for field in fields}


def _strategy_ids(state: AgentState) -> tuple[list[int], list[str]]:
    """把 LLM 选的 strategy_key 解析成 preview 需要的 strategy_ids。

    只接受**本会话已加载**清单里的 key（§13.1：LLM 只能选已加载策略）；解析不到
    就原样返回，由节点侧给出可读错误而不是让 preview 抛通用 400。
    """
    strategies = (state.get("security_context") or {}).get("strategies") or []
    wanted = [str(k).upper() for k in (state.get("security_strategy_keys") or []) if k]
    wanted = list(dict.fromkeys(wanted))

    matched: list[int] = []
    known: set[str] = set()
    for strategy in strategies:
        key = str(strategy.get("strategy_key") or "").upper()
        if key:
            known.add(key)
        if key in wanted and strategy.get("id") not in matched:
            matched.append(strategy["id"])

    unmatched = [key for key in wanted if key not in known]
    return matched, unmatched


def _target_args(state: AgentState) -> dict[str, Any]:
    """preview 目标：三者必须且只能给一个（§16.3）。"""
    context = state.get("security_context") or {}
    target_type = str(context.get("target_type") or state.get("target_type") or "API").upper()
    target_id = context.get("target_id") or (state.get("target_ids") or [None])[0]
    if target_type == "BUSINESS_ACTION":
        return {"business_action_id": target_id}
    return {"api_id": target_id}


def security_plan_generator_node(ctx: NodeContext, state: AgentState) -> dict:
    """生成安全计划预览（代码生成，不落 TestCase）。"""
    project_id = state["project_id"]

    if not state.get("security_context"):
        return set_error(
            state, "SECURITY_PLAN_FAILED",
            "缺少安全上下文，请重新描述要测试的目标",
        )

    strategy_ids, unmatched = _strategy_ids(state)
    if not strategy_ids:
        names = "、".join(unmatched) if unmatched else "未指定"
        return set_error(
            state, "SECURITY_PLAN_FAILED",
            f"没有可用的安全策略（{names}）：请在项目安全策略里启用后重试",
        )

    targets = _target_args(state)
    try:
        plan = security_tool.preview_plan(
            ctx.db, project_id, ctx.user,
            strategy_ids=strategy_ids,
            environment_id=state.get("environment_id"),
            **targets,
        )
        items = plan.get("items") or []
        if not items:
            return set_error(
                state, "SECURITY_PLAN_FAILED",
                "所选策略没有可执行的变异项（规则可能已停用，或目标不满足前置条件）",
            )

        plan_view = {
            "plan_id": plan.get("plan_id"),
            "status": plan.get("status"),
            "estimated_count": plan.get("estimated_count"),
            "truncated": plan.get("truncated"),
            # 按 API 目标生成时解析出的基线用例：让用户看清变异会落在哪条基线上。
            "baseline_case_id": plan.get("baseline_case_id"),
            "baseline_case_name": plan.get("baseline_case_name"),
            "target_type": next(iter(targets)),
            "strategy_keys": state.get("security_strategy_keys") or [],
            "items": [_pick(item, _PLAN_ITEM_FIELDS) for item in items],
        }
        return {
            "security_plan": plan_view,
            "security_plan_id": plan.get("plan_id"),
            "current_stage": "SECURITY_PLAN_REVIEW",
        }
    except (HTTPException, AppError) as exc:
        # AppError（如缺少可用基线用例，404）与 HTTPException 同一映射：404 → 目标不可用。
        code = "TARGET_NOT_FOUND" if getattr(exc, "status_code", 500) == 404 else "SECURITY_PLAN_FAILED"
        return set_error(state, code, f"安全计划生成失败：{exc}")
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "SECURITY_PLAN_FAILED", f"安全计划生成失败：{exc}")


def security_case_loader_node(ctx: NodeContext, state: AgentState) -> dict:
    """`EXECUTE_SECURITY_TEST`：只把 `case_type='SECURITY'` 的用例列到 review 面板。

    复用现有 `test_case_review` 暂停点，因此这里负责把待执行的安全用例装进
    `generated_test_cases`（execution 节点从 confirmed_case_ids 取 case id）。
    """
    project_id = state["project_id"]
    target_ids = state.get("target_ids") or []
    if not target_ids:
        return set_error(state, "TARGET_NOT_FOUND", "请指定要执行安全测试的接口或业务流程")

    try:
        rows: list[dict] = []
        for target_id in target_ids:
            rows.extend(
                c for c in test_asset_tool.get_existing_cases(
                    ctx.db, project_id, ctx.user,
                    target_type=str(state.get("target_type") or "API"),
                    target_id=target_id,
                )
                if str(c.get("case_type") or "").upper() == "SECURITY"
            )
        if not rows:
            return set_error(
                state, "TARGET_NOT_FOUND",
                "目标下没有安全测试用例（请先生成并确认安全计划）",
            )

        status = security_tool.security_case_status(
            ctx.db, project_id, ctx.user, test_case_ids=[c["id"] for c in rows],
        )
        cases = []
        for case in rows:
            info = status.get(case["id"]) or {}
            cases.append({
                **case,
                "case_type": "SECURITY",
                "security_case_id": info.get("security_case_id"),
                "security_confirmation_required": bool(info.get("confirmation_required")),
                "security_confirmation_status": (
                    "READY" if info.get("confirmed_at")
                    else ("PENDING_CONFIRM" if info.get("confirmation_required") else "READY")
                ),
            })
        return {
            "generated_test_cases": cases,
            "confirmed_case_ids": [c["id"] for c in cases],
            "current_stage": "TEST_CASE_REVIEW",
        }
    except HTTPException as exc:
        code = "TARGET_NOT_FOUND" if exc.status_code == 404 else "SECURITY_PLAN_FAILED"
        return set_error(state, code, f"安全用例加载失败：{exc.detail}")
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "SECURITY_PLAN_FAILED", f"安全用例加载失败：{exc}")


def security_plan_review_node(ctx: NodeContext, state: AgentState) -> dict:
    """安全计划 review 暂停标记（interrupt_before，正常流程下不会被执行）。"""
    return {}


def _int_list(values: list[Any] | None) -> list[int]:
    return [int(v) for v in (values or []) if isinstance(v, (int, str)) and str(v).isdigit()]


def _case_view(case_id: int, item: dict, security_case_id: int | None) -> dict:
    """把预览项 + TestCase id 组装成用例 review 面板需要的条目。"""
    requires_confirm = bool(item.get("confirmation_required"))
    return {
        "id": case_id,
        "security_case_id": security_case_id,
        "name": item.get("name"),
        "case_type": "SECURITY",
        "target_type": item.get("target_type") or "API",
        "api_id": item.get("api_id"),
        "business_action_id": item.get("business_action_id"),
        "mutation_type": item.get("mutation_type"),
        "expectation": item.get("expectation"),
        "severity": item.get("severity"),
        "risk_level": item.get("risk_level"),
        "security_confirmation_required": requires_confirm,
        "security_confirmation_status": "PENDING_CONFIRM" if requires_confirm else "READY",
        "blocked_reason": item.get("blocked_reason"),
    }


def security_case_materializer_node(ctx: NodeContext, state: AgentState) -> dict:
    """人工确认安全计划后落 TestCase（`confirm_security_plan` action 专用）。"""
    plan_id = state.get("security_plan_id")
    if not plan_id:
        return set_error(
            state, "SECURITY_PLAN_FAILED",
            "没有待确认的安全计划（请先生成安全计划）",
        )

    plan = state.get("security_plan") or {}
    items = list(plan.get("items") or [])
    payload = state.get("action_payload") or {}
    accepted = _int_list(payload.get("security_item_indexes") or payload.get("item_indexes"))
    # 缺省 = 全部未阻断项（阻断项缺变异配置，确认了也执行不了）。
    if not accepted:
        accepted = [int(i["index"]) for i in items if not i.get("blocked_reason")]
    if not accepted:
        return set_error(
            state, "SECURITY_PLAN_FAILED",
            "所有计划项都被阻断（缺少 Fixture），请补齐测试数据后重试",
        )

    try:
        result = security_tool.confirm_plan(
            ctx.db, int(plan_id), ctx.user, accepted_item_indexes=accepted,
        )
        accepted_set = set(accepted)
        # index 从 0 开始：不能用 `or -1` 兜底，否则第 0 条永远匹配不上。
        selected = [
            i for i in items
            if i.get("index") is not None and int(i["index"]) in accepted_set
        ]
        created_ids = result.get("created_case_ids") or []

        status = security_tool.security_case_status(
            ctx.db, state["project_id"], ctx.user, test_case_ids=created_ids,
        )
        cases = [
            _case_view(case_id, item, (status.get(case_id) or {}).get("security_case_id"))
            for case_id, item in zip(created_ids, selected)
        ]
        if not cases:
            return set_error(
                state, "SECURITY_PLAN_FAILED",
                "所选计划项没有生成用例（可能已全部被阻断，请调整策略或目标）",
            )

        pending = [c["id"] for c in cases if c["security_confirmation_required"]]
        return {
            "generated_test_cases": cases,
            "confirmed_case_ids": [c["id"] for c in cases],
            "security_plan": {**plan, "status": result.get("status")},
            "security_plan_id": None,
            "security_risk_pending": {
                "count": len(pending),
                "case_ids": pending,
                "message": (
                    f"其中 {len(pending)} 条为高风险用例，执行前需要人工确认"
                    if pending
                    else None
                ),
            },
            "current_stage": "TEST_CASE_REVIEW",
        }
    except HTTPException as exc:
        code = "PERMISSION_DENIED" if exc.status_code == 403 else "SECURITY_PLAN_FAILED"
        return set_error(state, code, f"安全用例保存失败：{exc.detail}")
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "SECURITY_PLAN_FAILED", f"安全用例保存失败：{exc}")


def security_risk_confirm_node(ctx: NodeContext, state: AgentState) -> dict:
    """人工高风险确认（`confirm_security_risk` action 专用，不进 LLM 工具参数）。

    缺省确认本会话里所有仍待确认的安全用例——确认动作本身是人工触发的，
    自动枚举只是省掉用户逐条勾选。已在 runner 里被跳过的高风险用例确认后才放行。
    """
    payload = state.get("action_payload") or {}
    wanted = _int_list(payload.get("security_case_ids") or payload.get("case_ids"))
    cases = state.get("generated_test_cases") or []

    if wanted:
        wanted_set = set(wanted)
        targets = [c for c in cases if c.get("id") in wanted_set]
    else:
        targets = [
            c for c in cases
            if c.get("security_confirmation_required")
            and c.get("security_confirmation_status") == "PENDING_CONFIRM"
        ]

    if not targets:
        return set_error(
            state, "SECURITY_PLAN_FAILED",
            "没有待确认的高风险安全用例",
        )

    confirmed: list[int] = []
    failed: list[str] = []
    for case in targets:
        security_case_id = case.get("security_case_id")
        if not security_case_id:
            failed.append(f"用例 {case.get('id')} 缺少安全扩展行")
            continue
        try:
            _CASE_SERVICE.confirm_risk(ctx.db, int(security_case_id), actor=ctx.user)
            confirmed.append(int(case["id"]))
        except HTTPException as exc:
            failed.append(f"用例 {case.get('id')}：{exc.detail}")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"用例 {case.get('id')}：{exc}")

    updated = [
        {
            **case,
            "security_confirmation_status": (
                "CONFIRMED" if case.get("id") in set(confirmed)
                else case.get("security_confirmation_status")
            ),
        }
        for case in cases
    ]
    if not confirmed:
        return set_error(
            state, "SECURITY_PLAN_FAILED",
            "高风险确认失败：" + "；".join(failed[:5]),
        )

    return {
        "generated_test_cases": updated,
        "confirmed_case_ids": [c["id"] for c in updated],
        "current_stage": "TEST_CASE_REVIEW",
        "security_risk_pending": {
            "count": sum(
                1 for c in updated
                if c.get("security_confirmation_status") == "PENDING_CONFIRM"
            ),
            "case_ids": [
                c["id"] for c in updated
                if c.get("security_confirmation_status") == "PENDING_CONFIRM"
            ],
            "confirmed": confirmed,
            "failed": failed,
            "message": f"已确认 {len(confirmed)} 条高风险用例" + (
                f"，{len(failed)} 条未确认" if failed else ""
            ),
        },
    }


__all__ = [
    "security_case_loader_node",
    "security_plan_generator_node",
    "security_plan_review_node",
    "security_case_materializer_node",
    "security_risk_confirm_node",
]
