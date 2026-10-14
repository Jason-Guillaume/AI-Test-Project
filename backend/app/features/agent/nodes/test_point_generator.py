"""TestPointGeneratorNode：生成结构化测试点 → 去重 → 落库。

- LLM（test_point.md）输出结构化 TestPoint 列表；
- `test_asset_tool.semantic_key` 归一化去重：与已有测试点同名的不重复生成；
- 经 `test_asset_tool.save_points` 落库（source_type=AI + agent_session_id +
  generation_version），**测试点先落库**以便用例生成时通过 test_point_id 建立关联；
- 进入 TEST_POINT_REVIEW 暂停点，由人工确认后再生成用例（§14 human review）。
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from pydantic import ValidationError

from app.features.agent.nodes._context import NodeContext
from app.features.agent.providers.llm_provider import LLMError
from app.features.agent.prompts import load_prompt
from app.features.agent.providers.sanitizer import sanitize_context
from app.features.agent.schemas import TestPointDraftList
from app.features.agent.services.session_service import next_generation_version
from app.features.agent.state import AgentState, set_error
from app.features.agent.tools import test_asset_tool
from app.features.agent.tools.test_asset_tool import semantic_key


def _dump(obj) -> str:
    return json.dumps(sanitize_context(obj), ensure_ascii=False, default=str)


def test_point_generator_node(ctx: NodeContext, state: AgentState) -> dict:
    project_id = state["project_id"]
    session_id = state["session_id"]
    try:
        user_content = (
            "## 测试计划\n" + _dump(state.get("test_plan")) + "\n\n"
            "## 接口上下文\n" + _dump(state.get("api_context")) + "\n\n"
            "## 业务上下文\n" + _dump(state.get("business_context")) + "\n\n"
            "## 可用测试策略（strategy_id 只能从下列 ID 中选取）\n"
            + _dump(state.get("strategy_context")) + "\n\n"
            "## 已有测试点（请勿重复生成同名 / 相似项）\n"
            + _dump((state.get("existing_test_context") or {}).get("points", []))
        )
        result = ctx.provider.generate_structured(
            load_prompt("test_point"), user_content, kind="test_points",
            history=state.get("messages"),
        )
        draft_list = TestPointDraftList.model_validate(result)

        # 去重：与已有测试点 semantic_key 相同的跳过（保留生成顺序）。
        existing_keys = {
            p.get("semantic_key", "")
            for p in (state.get("existing_test_context") or {}).get("points", [])
            if p.get("semantic_key")
        }
        unique: list = []
        for draft in draft_list.points:
            key = semantic_key(draft.name)
            if not key or key in existing_keys:
                continue
            unique.append(draft)
            existing_keys.add(key)

        if not unique:
            return {
                "generated_test_points": [],
                "confirmed_point_ids": [],
                "current_stage": "TEST_POINT_REVIEW",
            }

        gen_version = next_generation_version(ctx.db, session_id, message_type="TEST_POINTS")
        saved = test_asset_tool.save_points(
            ctx.db, project_id, ctx.user, unique,
            agent_session_id=session_id, generation_version=gen_version,
        )

        # 合并 DB id，供前端展示与用例关联。
        points_with_ids = []
        for i, draft in enumerate(unique):
            item = draft.model_dump()
            if i < len(saved):
                item["id"] = saved[i]["id"]
            points_with_ids.append(item)

        return {
            "generated_test_points": points_with_ids,
            "confirmed_point_ids": [],
            "generation_version": gen_version,
            "current_stage": "TEST_POINT_REVIEW",
        }
    except LLMError as exc:
        return set_error(state, exc.code, str(exc))
    except (ValueError, ValidationError) as exc:
        return set_error(state, "STRUCTURED_OUTPUT_INVALID", f"测试点输出不合法：{exc}")
    except HTTPException as exc:
        # 409 = 重名冲突（去重已尽力，残留冲突提示用户）；403 = 权限。
        code = (
            "TEST_POINT_VALIDATION_FAILED"
            if exc.status_code == 409
            else ("PERMISSION_DENIED" if exc.status_code == 403 else "CONTEXT_LOAD_FAILED")
        )
        return set_error(state, code, str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "TEST_POINT_VALIDATION_FAILED", f"测试点生成失败：{exc}")
