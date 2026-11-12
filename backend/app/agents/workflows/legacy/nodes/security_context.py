"""SecurityContextLoaderNode：加载安全测试上下文（Phase F，§13.3）。

只加载 §13.3 列出的最小集合：

- 目标 API 的 method/path/auth_type/参数摘要/body schema 摘要（沿用 api_catalog_tool）
- 该 API 绑定的**单个** Business Action + 所属 Flow 的动作顺序、State、Rule 标题
- 目标已有的 ACTIVE Fixture：只要 key / entity_type / 输出名（不要 Provider 配置，不要 Token）
- 本项目启用的安全策略与规则摘要（系统模板一并给出）
- 该 API 未关闭的 Finding 标题与严重级别，最多 20 条

与生成链共用一条限制：**一次一个目标**——多目标返回澄清，不猜。
所有数据经 `sanitize_context` 清洗后才写进 state（state 会进 prompt 与落库）。
"""

from __future__ import annotations

import json

from fastapi import HTTPException

from app.agents.workflows.legacy.nodes._context import NodeContext
from app.core.security.sanitizer import sanitize_context
from app.agents.workflows.legacy.state import AgentState, set_error
from app.tools.builtin import (
    api_catalog_tool,
    business_tool,
    fixture_tool,
    security_tool,
)

#: 参数 / 响应条数上限：够 Agent 选字段，不至于把整份接口定义灌进提示词。
_MAX_PARAMETERS = 30
_MAX_FINDINGS = 20


def _dump(obj) -> str:
    """将输入数据转换为可序列化的字典。"""
    return json.dumps(sanitize_context(obj), ensure_ascii=False, default=str)


def _api_brief(api: dict) -> dict:
    """接口摘要：method/path/auth_type + 参数与 body schema 的形状，不含取值。"""
    body = api.get("body") or {}
    return {
        "id": api.get("id"),
        "name": api.get("name"),
        "method": api.get("method"),
        "path": api.get("path"),
        "auth_type": api.get("auth_type"),
        "content_type": api.get("content_type"),
        "parameters": [
            {
                "name": p.get("name"),
                "location": p.get("location"),
                "type": p.get("type"),
                "required": bool(p.get("required")),
            }
            for p in (api.get("parameters") or [])[:_MAX_PARAMETERS]
        ],
        "body_type": body.get("body_type"),
        "body_schema": _schema_brief(body.get("schema_json") or {}),
        "response_codes": [r.get("status_code") for r in (api.get("responses") or [])],
    }


def _schema_brief(schema: dict, *, depth: int = 2) -> dict:
    """只保留字段名与类型：Agent 需要知道「有哪些字段可变异」，不需要示例值。"""
    if depth <= 0 or not isinstance(schema, dict):
        return {}
    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        return {"type": schema.get("type"), "required": schema.get("required") or []}
    out = {}
    for name, prop in list(properties.items())[:50]:
        if isinstance(prop, dict) and "properties" in prop:
            out[name] = {
                "type": prop.get("type"),
                "fields": list((prop.get("properties") or {}).keys())[:20],
            }
        else:
            out[name] = (prop or {}).get("type") if isinstance(prop, dict) else str(prop)
    return {"required": schema.get("required") or [], "properties": out}


def _flow_brief(flow_detail: dict) -> dict:
    """流程摘要：动作顺序 + State 标题 + Rule 标题（不要整棵无关流程）。"""
    actions = []
    for idx, action in enumerate(flow_detail.get("actions") or []):
        actions.append({
            "order": idx + 1,
            "id": action.get("id"),
            "name": action.get("name"),
            "action_key": action.get("action_key"),
            "states": [s.get("name") for s in (action.get("states") or []) if s.get("name")],
        })
    return {
        "flow_id": flow_detail.get("id") or flow_detail.get("flow_id"),
        "flow_name": flow_detail.get("name"),
        "actions": actions,
        "rule_titles": [
            r.get("name") for r in (flow_detail.get("rules") or []) if r.get("name")
        ],
    }


def _fixture_brief(fixtures: list[dict]) -> list[dict]:
    """Fixture 摘要：只要 key / entity_type / 输出名，绝不带 Provider 配置与输出值。"""
    return [
        {
            "fixture_key": f.get("fixture_key"),
            "entity_type": f.get("entity_type"),
            "outputs": f.get("outputs") or [],
        }
        for f in fixtures
    ]


def _finding_titles(findings: list[dict]) -> list[dict]:
    """未关闭 Finding 只留标题与严重级别（§14：evidence 不进提示词）。"""
    return [
        {"title": f.get("title"), "severity": f.get("severity"), "status": f.get("status")}
        for f in findings
    ]


def security_context_loader_node(ctx: NodeContext, state: AgentState) -> dict:
    """加载安全测试上下文，供 security_plan_generator 生成计划。

    多目标 → 返回澄清（§13.3「一次一个目标，不猜」）；不进入 FAILED，用户换一句即可继续。
    """
    project_id = state["project_id"]
    target_ids = state.get("target_ids") or []

    if len(target_ids) != 1:
        return {
            "intent": state.get("intent"),
            "clarify_question": (
                "安全测试一次只测一个目标，请只指定一个接口（或一个业务动作）"
            ),
            "current_stage": "CLARIFY",
        }

    target_id = target_ids[0]
    target_type = str(state.get("target_type") or "API").upper()

    try:
        api_brief: dict | None = None
        action_brief: dict | None = None
        flow_brief: dict | None = None
        api_id: int | None = None
        business_action_id: int | None = None

        if target_type == "BUSINESS_ACTION":
            action = business_tool.get_action(ctx.db, target_id, ctx.user, project_id=project_id)
            action_brief = action
            business_action_id = target_id
            flow_id = action.get("flow_id")
            if flow_id:
                flow_brief = _flow_brief(
                    business_tool.get_flow_detail(ctx.db, flow_id, ctx.user, project_id=project_id)
                )
        else:
            # 默认按 API 处理（target_type 缺失时给一次机会，而不是直接失败）。
            api_id = target_id
            api_brief = _api_brief(
                api_catalog_tool.get_api(ctx.db, target_id, ctx.user, project_id=project_id)
            )
            binding = business_tool.get_action_by_api(ctx.db, target_id, ctx.user, project_id=project_id)
            if binding:
                action_brief = binding
                if binding.get("flow_id"):
                    flow_brief = _flow_brief(
                        business_tool.get_flow_detail(
                            ctx.db, binding["flow_id"], ctx.user, project_id=project_id,
                        )
                    )

        strategies = security_tool.list_strategies(ctx.db, project_id, ctx.user)
        findings = security_tool.open_findings_brief(
            ctx.db, project_id, ctx.user, api_id=api_id, limit=_MAX_FINDINGS,
        )
        fixtures = _fixture_brief(fixture_tool.list_active_fixtures(ctx.db, project_id))

        context = {
            "target_type": "BUSINESS_ACTION" if business_action_id else "API",
            "target_id": business_action_id or api_id,
            "api": api_brief,
            "business_action": action_brief,
            "flow": flow_brief,
            "fixtures": fixtures,
            "strategies": strategies,
            "open_findings": _finding_titles(findings),
        }

        return {
            "security_context": sanitize_context(context),
            "security_finding_brief": findings,
            "current_stage": "CONTEXT_LOADING",
        }
    except HTTPException as exc:
        code = "TARGET_NOT_FOUND" if exc.status_code == 404 else "SECURITY_CONTEXT_FAILED"
        return set_error(state, code, f"安全上下文加载失败：{exc.detail}")
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "SECURITY_CONTEXT_FAILED", f"安全上下文加载失败：{exc}")


__all__ = ["security_context_loader_node"]
