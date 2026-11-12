"""IntentNode：意图识别 + 目标解析。

用 intent.md（system）把用户自然语言归类为下列意图之一，并解析被测目标。
候选目标（接口 / 业务流程列表）作为**业务数据**放入 user content，LLM 只能从中
选取 target_ids——未命中时返回 CLARIFY 提问，**不猜**危险操作（§35）。

Web 智能体二轮补充：意图 `INTERACTIVE_WEB_AUTHORING` 是否需要触发，取决于本 Agent
会话是否已绑定一个受控浏览器会话（state.web_agent_session_id）。该信号必须以**业务
数据**形式写进 user content——否则模型手上只有候选接口与业务流程，永远看不出应该
选它，observe→decide→act 链路即便写进 intent.md 也会在生产环境不可达。
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from pydantic import ValidationError

from app.agents.workflows.legacy.nodes._context import NodeContext
from app.agents.workflows.legacy.nodes.validator import assert_no_forbidden_fields
from app.llm import LLMError
from app.agents.prompts import load_prompt
from app.core.security.sanitizer import sanitize_context
from app.agents.session_schemas import IntentResult
from app.agents.workflows.legacy.state import AgentState, set_error
from app.tools.builtin import api_catalog_tool, business_tool, security_tool


def _dump(obj) -> str:
    """JSON 序列化（中文不转义），用于拼入 prompt 的业务数据段。"""
    return json.dumps(sanitize_context(obj), ensure_ascii=False, default=str)


def intent_node(ctx: NodeContext, state: AgentState) -> dict:
    """识别用户意图并更新智能体状态。"""
    project_id = state["project_id"]
    try:
        # 候选目标：供 LLM 解析 target_ids（只给 ID 级概要，细节由 context_loader 拉取）。
        apis = api_catalog_tool.search_api(ctx.db, project_id, ctx.user, page_size=30)
        flows = business_tool.list_flows(ctx.db, project_id, ctx.user, page_size=30)
        # 安全意图只给策略 key 与名称（不给规则脚本体）——变异清单由代码生成。
        strategies = security_tool.list_strategies(ctx.db, project_id, ctx.user)

        user_message = state.get("user_message") or ""
        # Web 受控会话绑定信号：这是模型判断是否选 INTERACTIVE_WEB_AUTHORING 的唯一依据。
        # state 里有 web_agent_session_id，但只写进 AGENT_INTENTS / 路由分支是不够的——
        # 模型看不到它，就会一直落到 CLARIFY。见 intent.md 该意图条目的触发条件。
        bound_session = state.get("web_agent_session_id")
        web_binding = (
            "## Web 受控会话绑定\n"
            f"本会话已绑定一个受控浏览器会话（session_id={bound_session}），可以打开真实页面"
            "并逐步探索、人工确认每一步。用户提出看页面 / 在页面上操作 / 交互式编写 Web 用例时，"
            "选 INTERACTIVE_WEB_AUTHORING。\n"
            if bound_session
            else "## Web 受控会话绑定\n"
            "本会话尚未绑定受控浏览器会话（浏览器会话需在控制台 Web UI 智能体页先启动并随消息"
            "传入 web_session_id）。用户只是泛泛问 Web 用例怎么写、而不是要求现在打开页面时，"
            "不要选 INTERACTIVE_WEB_AUTHORING——改用 CLARIFY 说明需要先启动浏览器会话。\n"
        )
        user_content = (
            "## 候选接口（只能从下列 ID 中选取 target_ids）\n"
            f"{_dump(apis.get('items', []))}\n\n"
            "## 候选业务流程（只能从下列 ID 中选取 target_ids）\n"
            f"{_dump(flows.get('items', []))}\n\n"
            "## 候选安全策略（security_strategy_keys 只能从下列 strategy_key 中选取）\n"
            f"{_dump([{'strategy_key': s.get('strategy_key'), 'name': s.get('name'), 'category': s.get('category')} for s in strategies])}\n\n"
            f"{web_binding}"
            f"## 用户消息\n{user_message}"
        )
        system = load_prompt("intent")
        result = ctx.provider.generate_structured(
            system, user_content, kind="intent", history=state.get("messages"),
        )
        assert_no_forbidden_fields(result)
        intent_result = IntentResult.model_validate(result)

        # 意图合法但 target 解析失败 → 转 CLARIFY（不猜）。
        needs_target = (
            "GENERATE_TEST_POINTS", "GENERATE_AND_EXECUTE", "GENERATE_SECURITY_TEST",
            "EXECUTE_SECURITY_TEST",
        )
        if intent_result.intent == "CLARIFY" or (
            intent_result.intent in needs_target and not intent_result.target_ids
        ):
            return {
                "intent": "CLARIFY",
                "clarify_question": intent_result.clarify_question
                or "请指定要测试的接口（如接口名 / 路径）或业务流程名称",
                "current_stage": "CLARIFY",
            }

        # EXECUTE_* 意图直接路由到 test_case_review 暂停点，需提前把 stage 设为
        # TEST_CASE_REVIEW，否则 intent_node 会覆写为 CONTEXT_LOADING 导致前端无按钮。
        stage = (
            "TEST_CASE_REVIEW"
            if intent_result.intent in ("EXECUTE_EXISTING_CASES", "EXECUTE_SECURITY_TEST")
            else "CONTEXT_LOADING"
        )

        return {
            "intent": intent_result.intent,
            "target_type": intent_result.target_type,
            "target_ids": intent_result.target_ids,
            "target_description": intent_result.target_description,
            "clarify_question": intent_result.clarify_question,
            "security_strategy_keys": intent_result.security_strategy_keys,
            "current_stage": stage,
        }
    except LLMError as exc:
        return set_error(state, exc.code, str(exc))
    except (ValueError, ValidationError) as exc:
        return set_error(state, "STRUCTURED_OUTPUT_INVALID", f"意图识别输出不合法：{exc}")
    except HTTPException as exc:
        code = "TARGET_NOT_FOUND" if exc.status_code == 404 else "INTENT_NOT_SUPPORTED"
        return set_error(state, code, str(exc.detail))
    except Exception as exc:  # noqa: BLE001 — 兜底，避免单节点异常拖垮整轮
        return set_error(state, "INTENT_NOT_SUPPORTED", f"意图识别失败：{exc}")
