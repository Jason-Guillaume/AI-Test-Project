"""QueryNode：查询已有测试资产（QUERY_TEST_ASSET，只读）。

按目标查询已有测试点 / 用例并汇总为文本摘要，供前端展示。结果写入 `analysis`
字段（复用 RESULT 消息通道）——查询与结果分析同属「只读产出」，phase 1 不单独建
消息类型；原始数据另存 `existing_test_context` 供前端展开查看。
"""

from __future__ import annotations

from fastapi import HTTPException

from app.features.agent.nodes._context import NodeContext
from app.features.agent.state import AgentState, set_error
from app.features.agent.tools import test_asset_tool


def query_node(ctx: NodeContext, state: AgentState) -> dict:
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
