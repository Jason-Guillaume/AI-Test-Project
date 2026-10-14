"""TestCaseGeneratorNode：基于**已确认**测试点生成结构化测试用例。

只对 confirmed_point_ids 对应的测试点生成（§14：人工确认后才生成用例）。
用例的 `test_point_id` 取自已落库测试点的 DB id，建立 测试点 → 用例 关联。

每条用例含子实体（preconditions / test_data / steps / assertions），子实体 schema
复用 test_management 的 *Create 模型（Pydantic 二次校验在 ValidatorNode）。
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from pydantic import ValidationError

from app.features.agent.nodes._context import NodeContext
from app.features.agent.providers.llm_provider import LLMError
from app.features.agent.prompts import load_prompt
from app.features.agent.providers.sanitizer import sanitize_context
from app.features.agent.schemas import TestCaseDraftList
from app.features.agent.state import AgentState, set_error


def _dump(obj) -> str:
    return json.dumps(sanitize_context(obj), ensure_ascii=False, default=str)


def test_case_generator_node(ctx: NodeContext, state: AgentState) -> dict:
    confirmed_ids = state.get("confirmed_point_ids") or []
    points = state.get("generated_test_points") or []
    # 仅保留已确认的测试点；未显式确认时（confirmed 为空但有生成点）视为全部确认。
    confirmed_points = (
        [p for p in points if p.get("id") in confirmed_ids]
        if confirmed_ids
        else [p for p in points if p.get("id")]
    )
    if not confirmed_points:
        return set_error(
            state, "NO_TEST_POINTS_CONFIRMED",
            "没有已确认的测试点，请先确认测试点或重新生成",
        )

    try:
        user_content = (
            "## 已确认测试点（为每个测试点生成一条用例，test_point_id 用其 id）\n"
            + _dump(confirmed_points)
            + "\n\n## 接口上下文\n" + _dump(state.get("api_context")) + "\n\n"
            + "## 业务上下文\n" + _dump(state.get("business_context")) + "\n\n"
            + "## 已有测试用例（请勿重复生成同名项）\n"
            + _dump((state.get("existing_test_context") or {}).get("cases", []))
        )
        result = ctx.provider.generate_structured(
            load_prompt("test_case"), user_content, kind="test_cases",
            history=state.get("messages"),
        )
        draft_list = TestCaseDraftList.model_validate(result)
        cases = [c.model_dump() for c in draft_list.cases]
        return {
            "generated_test_cases": cases,
            "confirmed_case_ids": [],
            "current_stage": "TEST_CASE_REVIEW",
        }
    except LLMError as exc:
        return set_error(state, exc.code, str(exc))
    except (ValueError, ValidationError) as exc:
        return set_error(state, "STRUCTURED_OUTPUT_INVALID", f"测试用例输出不合法：{exc}")
    except HTTPException as exc:
        return set_error(state, "TEST_CASE_VALIDATION_FAILED", str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "TEST_CASE_VALIDATION_FAILED", f"测试用例生成失败：{exc}")
