"""ValidatorNode：结构化用例的业务校验（§18）。

Pydantic 校验已在 TestCaseDraft / 子实体 *Create 模型完成（枚举、类型、长度）；
本节点做**跨字段**业务校验。校验失败允许 LLM **修复一次**（把错误清单回喂给模型），
仍失败则标记 TEST_CASE_VALIDATION_FAILED 返回用户（不静默通过）。

校验项：
1. 用例名非空
2. 每条用例至少 1 条断言
3. 断言 step_id（步骤下标）须落在本用例 steps 范围内
4. test_data 名称在用例内唯一
5. test_point_id 须指向已确认测试点
6. 用例名在项目内不重复（与已有用例 semantic_key 比对）
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from pydantic import ValidationError

from app.features.agent.nodes._context import NodeContext
from app.features.agent.providers.llm_provider import LLMError
from app.features.agent.providers.sanitizer import sanitize_context
from app.features.agent.schemas import TestCaseDraft, TestCaseDraftList
from app.features.agent.state import AgentState, set_error
from app.features.agent.tools.test_asset_tool import semantic_key


def _dump(obj) -> str:
    return json.dumps(sanitize_context(obj), ensure_ascii=False, default=str)


def _validate(drafts: list[TestCaseDraft], state: AgentState) -> list[dict]:
    """返回校验错误清单（空表示通过）。"""
    errors: list[dict] = []
    confirmed_ids = {p.get("id") for p in (state.get("generated_test_points") or []) if p.get("id")}
    existing_case_keys = {
        c.get("semantic_key", "")
        for c in (state.get("existing_test_context") or {}).get("cases", [])
        if c.get("semantic_key")
    }

    seen_names: set[str] = set()
    for idx, draft in enumerate(drafts):
        label = f"用例[{idx}]「{draft.name or '未命名'}」"
        if not draft.name or not draft.name.strip():
            errors.append({"field": f"cases[{idx}].name", "message": "用例名不能为空"})
            continue
        key = semantic_key(draft.name)
        if key in existing_case_keys or key in seen_names:
            errors.append({"field": f"cases[{idx}].name", "message": f"用例名「{draft.name}」已存在，请改名"})
        seen_names.add(key)

        if not draft.assertions:
            errors.append({"field": f"cases[{idx}].assertions", "message": "每条用例至少需要 1 条断言"})

        step_count = len(draft.steps)
        for a_idx, asn in enumerate(draft.assertions):
            if asn.step_id is not None:
                if not isinstance(asn.step_id, int) or not (0 <= asn.step_id < step_count):
                    errors.append({
                        "field": f"cases[{idx}].assertions[{a_idx}].step_id",
                        "message": f"step_id={asn.step_id} 超出本用例步骤范围（共 {step_count} 步）",
                    })

        seen_data_names: set[str] = set()
        for d_idx, data in enumerate(draft.test_data):
            name = (data.name or "").strip()
            if not name:
                errors.append({"field": f"cases[{idx}].test_data[{d_idx}].name", "message": "测试数据名称不能为空"})
                continue
            if name in seen_data_names:
                errors.append({"field": f"cases[{idx}].test_data[{d_idx}].name", "message": f"测试数据名称「{name}」在用例内重复"})
            seen_data_names.add(name)

        if draft.test_point_id is not None and draft.test_point_id not in confirmed_ids:
            errors.append({
                "field": f"cases[{idx}].test_point_id",
                "message": f"test_point_id={draft.test_point_id} 不在已确认测试点列表中",
            })
    return errors


_RETRY_SYSTEM = """你是接口测试平台的测试 Agent。下面是生成的测试用例及校验错误清单，请修复后重新输出完整 JSON。

只输出修复后的完整 JSON（格式与原输出一致），不要解释。修复要点：
- 断言 step_id 必须是本用例 steps 的合法下标（0 起），或删除该 step_id
- 每条用例至少 1 条断言
- 用例名 / 测试数据名称不能重复
- test_point_id 只能取自已确认测试点 ID
"""


def validator_node(ctx: NodeContext, state: AgentState) -> dict:
    drafts_data = state.get("generated_test_cases") or []
    if not drafts_data:
        return {"validation_errors": [], "current_stage": "TEST_CASE_REVIEW"}

    try:
        drafts = [TestCaseDraft.model_validate(d) for d in drafts_data]
        errors = _validate(drafts, state)

        if not errors:
            return {"validation_errors": []}

        # 修复一次：把错误清单回喂 LLM（§18 允许一次修复）。
        fix_user = (
            "## 原始用例\n" + _dump(drafts_data) + "\n\n"
            "## 校验错误\n" + _dump(errors)
        )
        try:
            fixed_result = ctx.provider.generate_structured(
                _RETRY_SYSTEM, fix_user, kind="test_cases",
            )
            fixed_list = TestCaseDraftList.model_validate(fixed_result)
            fixed_drafts = [c.model_dump() for c in fixed_list.cases]
            fixed_py = [TestCaseDraft.model_validate(d) for d in fixed_drafts]
            fixed_errors = _validate(fixed_py, state)
            if not fixed_errors:
                return {"generated_test_cases": fixed_drafts, "validation_errors": []}
            errors = fixed_errors
        except (LLMError, ValueError, ValidationError):
            pass  # 修复失败，保留原始错误返回

        return set_error(
            state, "TEST_CASE_VALIDATION_FAILED",
            f"用例校验未通过：{'; '.join(e['message'] for e in errors[:5])}",
        )
    except (ValueError, ValidationError) as exc:
        return set_error(state, "STRUCTURED_OUTPUT_INVALID", f"用例结构不合法：{exc}")
    except HTTPException as exc:
        return set_error(state, "TEST_CASE_VALIDATION_FAILED", str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "TEST_CASE_VALIDATION_FAILED", f"用例校验失败：{exc}")
