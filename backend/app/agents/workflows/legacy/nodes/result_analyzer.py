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

from app.agents.workflows.legacy.nodes._context import NodeContext
from app.agents.workflows.legacy.nodes.validator import assert_no_forbidden_fields
from app.llm import LLMError
from app.agents.prompts import load_prompt
from app.core.security.sanitizer import sanitize_context
from app.agents.session_schemas import ResultAnalysis
from app.agents.workflows.legacy.state import AgentState, set_error
from app.tools.builtin import execution_tool, security_tool


def _dump(obj) -> str:
    """将输入数据转换为可序列化的字典。"""
    return json.dumps(sanitize_context(obj), ensure_ascii=False, default=str)


def _load_security_findings(ctx: NodeContext, state: AgentState, run_id: int) -> list[dict]:
    """本 Run 的未关闭 Finding 摘要（脱敏、不含 evidence）。

    读失败不影响执行结果分析本身：Finding 是附加信息，不是分析的输入依赖。
    """
    try:
        return security_tool.open_findings_brief(
            ctx.db, state["project_id"], ctx.user, test_run_id=run_id,
        )
    except Exception as exc:  # noqa: BLE001
        return []


def result_analyzer_node(ctx: NodeContext, state: AgentState) -> dict:
    """分析执行结果并更新智能体状态。"""
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

        findings = _load_security_findings(ctx, state, run_id)

        user_content = (
            "## 执行记录\n" + _dump(run) + "\n\n"
            "## 逐用例执行详情\n" + _dump(executions.get("items", [])) + "\n\n"
            "## 本次执行的未关闭安全 Finding（仅供复核，不代表已确认漏洞）\n" + _dump(findings)
        )
        result = ctx.provider.generate_structured(
            load_prompt("result_analysis"), user_content, kind="result_analysis",
            history=state.get("messages"),
        )
        assert_no_forbidden_fields(result)
        analysis = ResultAnalysis.model_validate(result)
        return {
            # security_findings 从代码路径（Finding 表）来，不来自 LLM：LLM 的 numbers
            # 不可信，Finding 状态也不能由 LLM 改写（§二十四）。
            "analysis": {**analysis.model_dump(), "security_findings": findings},
            "security_finding_brief": findings,
            "current_stage": "COMPLETED",
        }
    except LLMError as exc:
        return set_error(state, exc.code, str(exc))
    except (ValueError, ValidationError) as exc:
        return set_error(state, "STRUCTURED_OUTPUT_INVALID", f"分析结果不合法：{exc}")
    except HTTPException as exc:
        code = "TARGET_NOT_FOUND" if exc.status_code == 404 else "EXECUTION_FAILED"
        return set_error(state, code, str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "EXECUTION_FAILED", f"结果分析失败：{exc}")
