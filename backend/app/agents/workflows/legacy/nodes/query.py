"""QueryNode：查询已有测试资产（QUERY_TEST_ASSET）与安全 Finding（Phase F，只读）。

按目标查询已有测试点 / 用例并汇总为文本摘要，供前端展示。结果写入 `analysis`
字段（复用 RESULT 消息通道）——查询与结果分析同属「只读产出」，phase 1 不单独建
消息类型；原始数据另存 `existing_test_context` 供前端展开查看。

QUERY_SECURITY_FINDING 走 `security_tool.list_findings`：只给摘要（title/severity/
status/mutation_type），**不含 evidence**——证据只在 Finding 详情页按需取（§十四）。
"""

from __future__ import annotations

from fastapi import HTTPException

from app.agents.workflows.legacy.nodes._context import NodeContext
from app.agents.workflows.legacy.state import AgentState, set_error
from app.tools.builtin import security_tool, test_asset_tool


def _query_findings(ctx: NodeContext, state: AgentState) -> dict:
    """安全 Finding 只读查询：目标为 API 时按 api_id 过滤，否则查项目全量。"""
    target_ids = state.get("target_ids") or []
    api_id = target_ids[0] if (state.get("target_type") == "API" and target_ids) else None
    items = security_tool.open_findings_brief(
        ctx.db, state["project_id"], ctx.user, api_id=api_id,
    )
    scope = f"接口 API#{api_id}" if api_id else "本项目"
    summary = f"{scope} 下有 {len(items)} 条未关闭安全 Finding（OPEN / CONFIRMED）"
    return {
        "analysis": {"summary": summary, "data": {"findings": items}},
        "security_finding_brief": items,
        "current_stage": "COMPLETED",
    }


def query_node(ctx: NodeContext, state: AgentState) -> dict:
    """根据用户查询补充所需的测试上下文。"""
    # QUERY_SECURITY_FINDING 不要求 target（可查项目全量 Finding）。
    if state.get("intent") == "QUERY_SECURITY_FINDING":
        try:
            return _query_findings(ctx, state)
        except HTTPException as exc:
            return set_error(state, "TARGET_NOT_FOUND", str(exc.detail))
        except Exception as exc:  # noqa: BLE001
            return set_error(state, "CONTEXT_LOAD_FAILED", f"查询 Finding 失败：{exc}")

    project_id = state["project_id"]
    target_type = state.get("target_type")
    target_ids = state.get("target_ids") or []
    if not target_type or not target_ids:
        return set_error(state, "TARGET_NOT_FOUND", "请指定查询范围（接口或业务流程）")

    try:
        points = test_asset_tool.get_existing_points(
            ctx.db, project_id, ctx.user, target_type=target_type, target_id=target_ids[0],
        )
        cases = test_asset_tool.get_existing_cases(
            ctx.db, project_id, ctx.user, target_type=target_type, target_id=target_ids[0],
        )
        summary = f"目标 {target_type}#{target_ids[0]} 下有 {len(points)} 条测试点、{len(cases)} 条测试用例"
        return {
            "analysis": {"summary": summary, "data": {"points": points, "cases": cases}},
            "existing_test_context": {
                "points": points,
                "cases": cases,
            },
            "current_stage": "COMPLETED",
        }
    except HTTPException as exc:
        return set_error(state, "TARGET_NOT_FOUND", str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "CONTEXT_LOAD_FAILED", f"查询失败：{exc}")
