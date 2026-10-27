"""ReportGeneratorNode：分析后自动生成正式报告（§五/§九/§二四）。

调用 report_tool.generate_report（包装 ReportService.build_report：代码统计 + LLM 总结），
生成后取脱敏 brief 写入 state，阶段推进到 REPORT_REVIEW（interrupt 暂停，等人工确认是否
触发飞书通知）。报告统计由代码计算，AI 只做总结（§五）；AI 总结失败报告仍 COMPLETED（§九），
节点据此不阻断——brief 仍可取到（ai_summary 可能为 None）。
"""

from __future__ import annotations

from fastapi import HTTPException

from app.features.agent.nodes._context import NodeContext
from app.features.agent.state import AgentState, set_error
from app.features.agent.tools import report_tool
from app.shared.errors import AppError


def report_generator_node(ctx: NodeContext, state: AgentState) -> dict:
    """根据执行结果生成测试报告。"""
    project_id = state["project_id"]
    run_id = state.get("test_run_id")
    if not run_id:
        return set_error(state, "EXECUTION_FAILED", "没有可生成报告的执行记录（请先执行测试）")
    try:
        resp = report_tool.generate_report(ctx.db, run_id, ctx.user, provider=ctx.provider)
        report_id = resp.get("report_id")
        if not report_id:
            return set_error(state, "REPORT_GENERATION_FAILED", "报告生成未返回报告ID")
        brief = report_tool.get_report_brief(ctx.db, report_id, ctx.user)
        return {"report_id": report_id, "report_brief": brief, "current_stage": "REPORT_REVIEW"}
    except AppError as exc:
        return set_error(state, exc.code or "REPORT_GENERATION_FAILED", exc.message)
    except HTTPException as exc:
        return set_error(state, "REPORT_GENERATION_FAILED", str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "REPORT_GENERATION_FAILED", f"报告生成失败：{exc}")
