"""SaveAssetNode：落库测试用例（含子实体）。

测试点已在 TestPointGeneratorNode 落库（供用例关联）；本节点落库**用例**及其
preconditions / test_data / steps / assertions，携带 source_type=AI + agent_session_id
+ generation_version（§11 追溯）。落库后进入 TEST_CASE_REVIEW 暂停点，由人工
确认执行（§14 human review）。

断言的 step_id 由 `test_asset_tool._rebase_assertion_steps` 按步骤下标回填为真实
主键（LLM 无法预知自增 ID）。
"""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError

from app.agents.workflows.legacy.nodes._context import NodeContext
from app.llm import LLMError  # noqa: F401 — 保持 except 一致
from app.tools.builtin.test_management.contracts import TestCaseDraft
from app.agents.services.session_service import next_generation_version
from app.agents.workflows.legacy.state import AgentState, set_error
from app.tools.builtin import test_asset_tool


def save_asset_node(ctx: NodeContext, state: AgentState) -> dict:
    """保存资产节点。"""
    project_id = state["project_id"]
    session_id = state["session_id"]
    drafts_data = state.get("generated_test_cases") or []
    if not drafts_data:
        return set_error(
            state, "TEST_CASE_VALIDATION_FAILED",
            "没有可保存的测试用例，请重新生成",
        )

    try:
        drafts = [TestCaseDraft.model_validate(d) for d in drafts_data]
        gen_version = next_generation_version(ctx.db, session_id, message_type="TEST_CASES")
        saved = test_asset_tool.save_cases(
            ctx.db, project_id, ctx.user, drafts,
            agent_session_id=session_id, generation_version=gen_version,
        )
        # 合并 DB id 供前端展示与执行选择。
        cases_with_ids = []
        for i, draft in enumerate(drafts):
            item = draft.model_dump()
            if i < len(saved):
                item["id"] = saved[i]["id"]
            cases_with_ids.append(item)
        return {
            "generated_test_cases": cases_with_ids,
            "confirmed_case_ids": [c["id"] for c in saved],
            "generation_version": gen_version,
            "current_stage": "TEST_CASE_REVIEW",
        }
    except (ValueError, ValidationError) as exc:
        return set_error(state, "STRUCTURED_OUTPUT_INVALID", f"用例结构不合法：{exc}")
    except HTTPException as exc:
        code = (
            "TEST_CASE_VALIDATION_FAILED"
            if exc.status_code == 409
            else ("PERMISSION_DENIED" if exc.status_code == 403 else "TEST_CASE_VALIDATION_FAILED")
        )
        return set_error(state, code, str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "TEST_CASE_VALIDATION_FAILED", f"用例保存失败：{exc}")
