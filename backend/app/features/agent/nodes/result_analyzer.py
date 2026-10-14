"""ResultAnalyzerNode：执行结果分析（§13 只分析，不宣称「发现 Bug」）。

读取 TestRun + 各 CaseExecution（含断言结果 / 脱敏快照 / error_code），调
result_analysis.md 输出 `{summary, issues[], recommendation}`。issue.severity
区分 POTENTIAL_BUG / TEST_DATA_ISSUE / EXECUTION_ERROR / ASSERTION_FAILURE / UNKNOWN
——**POTENTIAL_BUG 仅表示「值得人工复核」**，不宣称缺陷（§13）。

无 test_run_id 时（如直接发「分析结果」但从未执行）返回友好错误而非臆测。
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from pydantic import ValidationError

from app.features.agent.nodes._context import NodeContext
from app.features.agent.providers.llm_provider import LLMError
from app.features.agent.prompts import load_prompt
from app.features.agent.providers.sanitizer import sanitize_context
from app.features.agent.schemas import ResultAnalysis
from app.features.agent.state import AgentState, set_error
from app.features.agent.tools import execution_tool


def _dump(obj) -> str:
    return json.dumps(sanitize_context(obj), ensure_ascii=False, default=str)


def result_analyzer_node(ctx: NodeContext, state: AgentState) -> dict:
    project_id = state["project_id"]
    run_id = state.get("test_run_id")

    if not run_id:
        return set_error(
            state, "EXECUTION_FAILED",
            "没有可分析的执行记录（请先执行测试用例）",
        )

    try:
        run = execution_tool.get_test_run(ctx.db, run_id, ctx.user, project_id=project_id)
        executions = execution_tool.get_case_executions(ctx.db, run_id, ctx.user, project_id=project_id)

        user_content = (
            "## 执行记录\n" + _dump(run) + "\n\n"
            "## 逐用例执行详情\n" + _dump(executions.get("items", []))
        )
        result = ctx.provider.generate_structured(
            load_prompt("result_analysis"), user_content, kind="result_analysis",
            history=state.get("messages"),
        )
        analysis = ResultAnalysis.model_validate(result)
        return {"analysis": analysis.model_dump(), "current_stage": "COMPLETED"}
    except LLMError as exc:
        return set_error(state, exc.code, str(exc))
    except (ValueError, ValidationError) as exc:
        return set_error(state, "STRUCTURED_OUTPUT_INVALID", f"分析结果不合法：{exc}")
    except HTTPException as exc:
        code = "TARGET_NOT_FOUND" if exc.status_code == 404 else "EXECUTION_FAILED"
        return set_error(state, code, str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "EXECUTION_FAILED", f"结果分析失败：{exc}")
