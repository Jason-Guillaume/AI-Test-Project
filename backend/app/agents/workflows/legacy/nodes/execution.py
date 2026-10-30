"""ExecuteNode：调用现有执行链路（§13 不重新实现执行器）。

从 action_payload / state 取 confirmed_case_ids + environment_id，调
`execution_tool.create_test_run`——该 tool 建**临时** TestPlan + TestSuite 后调用
现有 `RunService.create_and_execute_run`（复用 TestCaseExecutor / 断言引擎 /
CaseExecution 落库）。节点本身不触碰执行细节。

执行环境由**人工确认**（execute action 必带 environment_id）：§14 human review，
Agent 不自行选择环境。
"""

from __future__ import annotations

from fastapi import HTTPException

from app.agents.workflows.legacy.nodes._context import NodeContext
from app.agents.workflows.legacy.state import AgentState, set_error
from app.tools.builtin import execution_tool


def execution_node(ctx: NodeContext, state: AgentState) -> dict:
    """执行已确认的测试步骤并记录结果。"""
    project_id = state["project_id"]
    session_id = state["session_id"]
    payload = state.get("action_payload") or {}

    # 用例：优先用本次 action 的 case_ids，否则用已保存用例的全部 id。
    case_ids = payload.get("case_ids") or state.get("confirmed_case_ids") or [
        c["id"] for c in (state.get("generated_test_cases") or []) if c.get("id")
    ]
    env_id = payload.get("environment_id") or state.get("environment_id")

    if not case_ids:
        return set_error(
            state, "NO_CASES_SELECTED",
            "未选择要执行的测试用例（请在用例 review 中选择用例后执行）",
        )
    if not env_id:
        return set_error(
            state, "NO_ENVIRONMENT",
            "未指定执行环境（请选择环境后执行）",
        )

    try:
        run = execution_tool.create_test_run(
            ctx.db, project_id, ctx.user,
            case_ids=case_ids, environment_id=env_id, session_id=session_id,
        )
        return {
            "test_run_id": run["id"],
            "execution_result": run,
            "confirmed_case_ids": case_ids,
            "environment_id": env_id,
            "current_stage": "ANALYZING",
        }
    except HTTPException as exc:
        code = (
            "PERMISSION_DENIED" if exc.status_code == 403
            else ("TARGET_NOT_FOUND" if exc.status_code == 404 else "EXECUTION_FAILED")
        )
        return set_error(state, code, str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "EXECUTION_FAILED", f"执行失败：{exc}")
