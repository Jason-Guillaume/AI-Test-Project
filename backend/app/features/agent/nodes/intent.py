"""IntentNode：意图识别 + 目标解析。

用 intent.md（system）把用户自然语言归类为 7 类意图之一，并解析被测目标。
候选目标（接口 / 业务流程列表）作为**业务数据**放入 user content，LLM 只能从中
选取 target_ids——未命中时返回 CLARIFY 提问，**不猜**危险操作（§35）。
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from pydantic import ValidationError

from app.features.agent.nodes._context import NodeContext
from app.features.agent.nodes.validator import assert_no_forbidden_fields
from app.features.agent.providers.llm_provider import LLMError
from app.features.agent.prompts import load_prompt
from app.features.agent.providers.sanitizer import sanitize_context
from app.features.agent.schemas import IntentResult
from app.features.agent.state import AgentState, set_error
from app.features.agent.tools import api_catalog_tool, business_tool, security_tool


def _dump(obj) -> str:
    """JSON 序列化（中文不转义），用于拼入 prompt 的业务数据段。"""
    return json.dumps(sanitize_context(obj), ensure_ascii=False, default=str)


def intent_node(ctx: NodeContext, state: AgentState) -> dict:
    project_id = state["project_id"]
    try:
        # 候选目标：供 LLM 解析 target_ids（只给 ID 级概要，细节由 context_loader 拉取）。
        apis = api_catalog_tool.search_api(ctx.db, project_id, ctx.user, page_size=30)
        flows = business_tool.list_flows(ctx.db, project_id, ctx.user, page_size=30)
        # 安全意图只给策略 key 与名称（不给规则脚本体）——变异清单由代码生成。
        strategies = security_tool.list_strategies(ctx.db, project_id, ctx.user)

        user_message = state.get("user_message") or ""
        user_content = (
            "## 候选接口（只能从下列 ID 中选取 target_ids）\n"
            f"{_dump(apis.get('items', []))}\n\n"
            "## 候选业务流程（只能从下列 ID 中选取 target_ids）\n"
            f"{_dump(flows.get('items', []))}\n\n"
            "## 候选安全策略（security_strategy_keys 只能从下列 strategy_key 中选取）\n"
            f"{_dump([{'strategy_key': s.get('strategy_key'), 'name': s.get('name'), 'category': s.get('category')} for s in strategies])}\n\n"
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
