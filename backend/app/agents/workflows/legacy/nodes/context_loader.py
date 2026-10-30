"""ContextLoaderNode：按目标反查**最小**上下文（§6/§7/§8）。

原则：**只拉当前 target 相关**的数据，禁止整库灌入（控制 token）。
- API：接口详情 + 所属业务动作 / 流程（若有绑定）
- BUSINESS_FLOW：单次往返拿完整流程树（actions + 子配置 + 规则）
- BUSINESS_ACTION：动作 → 流程详情 + 规则
- Mock：本项目已配置的 Mock 场景清单（独立于目标，供 required_mocks 引用）

所有上下文经 `sanitizer.sanitize_context()` 脱敏后入 prompt（§34）。
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.agents.workflows.legacy.nodes._context import NodeContext
from app.core.security.sanitizer import sanitize_context
from app.agents.workflows.legacy.state import AgentState, set_error
from app.tools.builtin import (
    api_catalog_tool,
    business_tool,
    fixture_tool,
    mock_tool,
    test_asset_tool,
)


def context_loader_node(ctx: NodeContext, state: AgentState) -> dict:
    """加载项目、用户和测试相关上下文。"""
    project_id = state["project_id"]
    target_type = state.get("target_type")
    target_ids = state.get("target_ids") or []

    if not target_ids:
        return {
            "intent": "CLARIFY",
            "clarify_question": "请指定要测试的接口或业务流程",
            "current_stage": "CLARIFY",
        }
    # 第一阶段仅支持单目标：多目标显式拦截，避免静默丢弃
    if len(target_ids) > 1:
        return set_error(
            state, "TARGET_NOT_FOUND",
            "当前仅支持单个测试目标，请一次指定一个接口或业务流程",
        )
    target_id = target_ids[0]

    # 可用 Fixture 清单独立于目标上下文加载：失败按空列表处理，不阻断其他意图。
    fixtures_payload: dict[str, Any]
    try:
        fixtures_payload = {
            "available_fixtures": sanitize_context(
                fixture_tool.list_active_fixtures(ctx.db, project_id)
            ),
            "available_fixtures_ok": True,
        }
    except Exception:  # noqa: BLE001 - 清单缺失只是让 Agent 拿不到建议，不应报错终止。
        fixtures_payload = {"available_fixtures": [], "available_fixtures_ok": False}

    # 可用 Mock 清单同样独立加载：项目没配 Mock 时给空列表，不阻断意图流转。
    mocks_payload: dict[str, Any]
    try:
        mocks_payload = {
            "available_mocks": sanitize_context(
                mock_tool.list_mock_scenarios(ctx.db, project_id, ctx.user)
            ),
            "available_mocks_ok": True,
        }
    except Exception:  # noqa: BLE001 - 同上：清单缺失不阻断其他意图。
        mocks_payload = {"available_mocks": [], "available_mocks_ok": False}

    try:
        api_context = None
        business_context = None

        if target_type == "API":
            api_context = api_catalog_tool.get_api(
                ctx.db, target_id, ctx.user, project_id=project_id,
            )
            action = business_tool.get_action_by_api(
                ctx.db, target_id, ctx.user, project_id=project_id,
            )
            if action is not None:
                flow_detail = business_tool.get_flow_detail(
                    ctx.db, action["flow_id"], ctx.user, project_id=project_id,
                )
                business_context = {
                    "action": action,
                    "flow": flow_detail,
                    "rules": business_tool.get_rules(
                        ctx.db, project_id, ctx.user, flow_id=action["flow_id"],
                    ),
                }
        elif target_type == "BUSINESS_FLOW":
            flow_detail = business_tool.get_flow_detail(
                ctx.db, target_id, ctx.user, project_id=project_id,
            )
            business_context = {
                "flow": flow_detail,
                "rules": business_tool.get_rules(
                    ctx.db, project_id, ctx.user, flow_id=target_id,
                ),
            }
        elif target_type == "BUSINESS_ACTION":
            action_info = business_tool.get_action(
                ctx.db, target_id, ctx.user, project_id=project_id,
            )
            flow_detail = business_tool.get_flow_detail(
                ctx.db, action_info["flow_id"], ctx.user, project_id=project_id,
            )
            business_context = {
                "action": action_info,
                "flow": flow_detail,
                "rules": business_tool.get_rules(
                    ctx.db, project_id, ctx.user, action_id=target_id,
                ),
            }
        else:
            msg = "无法确定被测对象类型，请指定接口或业务流程" if target_type is None else f"不支持的被测对象类型：{target_type}"
            return set_error(state, "TARGET_NOT_FOUND", msg)

        strategies = test_asset_tool.get_strategies(ctx.db, project_id, ctx.user)
        existing_test_context = {
            "points": test_asset_tool.get_existing_points(
                ctx.db, project_id, ctx.user, target_type=target_type, target_id=target_id,
            ),
            "cases": test_asset_tool.get_existing_cases(
                ctx.db, project_id, ctx.user, target_type=target_type, target_id=target_id,
            ),
        }

        return {
            "api_context": sanitize_context(api_context),
            "business_context": sanitize_context(business_context),
            "strategy_context": sanitize_context(strategies.get("items", [])),
            "existing_test_context": sanitize_context(existing_test_context),
            **fixtures_payload,
            **mocks_payload,
            "current_stage": "PLANNING",
        }
    except HTTPException as exc:
        code = "TARGET_NOT_FOUND" if exc.status_code == 404 else "CONTEXT_LOAD_FAILED"
        return set_error(state, code, str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "CONTEXT_LOAD_FAILED", f"上下文加载失败：{exc}")
