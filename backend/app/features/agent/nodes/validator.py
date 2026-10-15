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
7. required_fixtures 的 key 必须是当前项目可见且 ACTIVE 的 Fixture（§13：Agent 只能
   引用已注册 Fixture，不能生成或执行 SQL）；test_data 的 FIXTURE 绑定必须指向已声明
   的 key 与该 Fixture 的输出契约
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
    # 优先用已确认测试点 ID；为空但生成点非空时回退全量（与 test_case_generator 口径一致）
    confirmed_ids = set(state.get("confirmed_point_ids") or [])
    if not confirmed_ids:
        confirmed_ids = {p.get("id") for p in (state.get("generated_test_points") or []) if p.get("id")}
    existing_case_keys = {
        c.get("semantic_key", "")
        for c in (state.get("existing_test_context") or {}).get("cases", [])
        if c.get("semantic_key")
    }

    # Fixture 清单加载失败（ok=False）时不校验：拿不到清单不代表用例写错了。
    fixture_check_ok = bool(state.get("available_fixtures_ok"))
    available_fixtures = state.get("available_fixtures") or []
    available_keys = {
        f.get("fixture_key") for f in available_fixtures if f.get("fixture_key")
    }
    outputs_by_key = {
        f.get("fixture_key"): [o for o in (f.get("outputs") or []) if o]
        for f in available_fixtures if f.get("fixture_key")
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

        if fixture_check_ok:
            declared = {(k or "").strip() for k in (draft.required_fixtures or []) if (k or "").strip()}
            missing = sorted(declared - available_keys)
            if missing:
                # LLM 无法造出未注册的 Fixture，这里不是格式问题，不能靠修复重试解决。
                errors.append({
                    "field": f"cases[{idx}].required_fixtures",
                    "message": f"当前缺少 {', '.join(missing)} Fixture",
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

            if fixture_check_ok and (data.source_type or "").upper() == "FIXTURE":
                cfg = data.config_json or {}
                fk = str(cfg.get("fixture_key") or "").strip()
                out = str(cfg.get("output") or "").strip()
                if fk not in declared:
                    errors.append({
                        "field": f"cases[{idx}].test_data[{d_idx}].config_json",
                        "message": f"测试数据「{name}」引用的 Fixture {fk or '(空)'} 未在 required_fixtures 中声明",
                    })
                elif fk and out:
                    allowed = outputs_by_key.get(fk) or []
                    if allowed and out not in allowed:
                        errors.append({
                            "field": f"cases[{idx}].test_data[{d_idx}].config_json",
                            "message": f"测试数据「{name}」引用的输出 {out} 不在 Fixture {fk} 的输出契约里（可用：{'、'.join(allowed) or '无'}）",
                        })

        if draft.test_point_id is not None and draft.test_point_id not in confirmed_ids:
            errors.append({
                "field": f"cases[{idx}].test_point_id",
                "message": f"test_point_id={draft.test_point_id} 不在已确认测试点列表中",
            })
    return errors


def _has_unresolvable_fixture_error(errors: list[dict]) -> bool:
    """是否为「引用了不存在的 Fixture」——LLM 改不动，必须直接拒绝。"""
    return any(str(e.get("field", "")).endswith("required_fixtures") for e in errors)


_RETRY_SYSTEM = """你是接口测试平台的测试 Agent。下面是生成的测试用例及校验错误清单，请修复后重新输出完整 JSON。

只输出修复后的完整 JSON（格式与原输出一致），不要解释。修复要点：
- 断言 step_id 必须是本用例 steps 的合法下标（0 起），或删除该 step_id
- 每条用例至少 1 条断言
- 用例名 / 测试数据名称不能重复
- test_point_id 只能取自已确认测试点 ID
- required_fixtures 只能引用已给出的 fixture_key；FIXTURE 测试数据要指向已声明的 key 与它的输出名
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

        if _has_unresolvable_fixture_error(errors):
            # 缺少的 Fixture 无法靠改写用例补齐（平台不代 Agent 造 Fixture）：直接拒绝，
            # 提示语保留「当前缺少 XXX Fixture」，不做修复重试。
            return set_error(
                state, "TEST_CASE_VALIDATION_FAILED",
                f"用例校验未通过：{'; '.join(e['message'] for e in errors[:5])}",
            )

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
