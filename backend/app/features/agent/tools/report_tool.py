"""Agent Tool 层：测试报告（§三二）。

Agent **不重新实现**报告统计。`generate_report` 包装 `ReportService.build_report`
（代码统计 total/passed/failed/.../pass_rate/风险 + LLM 结构化总结）；`get_report_brief`
取脱敏摘要供 Agent「查看报告 / 总结报告」（§二四 报告闭环）。

权限：写 member+（build_report 内 require_writable_project）；读 viewer+（get_report_orm）。
统计字段由代码计算，AI 只做总结（§五）；AI 总结失败报告仍 COMPLETED（§九）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.features.agent.providers.sanitizer import sanitize_context
from app.features.reports.services import ReportService
from app.models.identity import User

_REPORT = ReportService()


def generate_report(db: Session, run_id: int, actor: User, *, provider: Any = None) -> dict:
    """为一次执行生成正式报告，返回 {report_id, status}。"""
    resp = _REPORT.build_report(db, run_id, actor=actor, generate_ai_summary=True, provider=provider)
    return resp.model_dump(mode="json")


def get_report_brief(db: Session, report_id: int, user: User) -> dict:
    """取报告脱敏摘要供 Agent 查看（统计由代码计算，不含 webhook 等敏感信息）。

    含 AI 总结 overview 供 Agent 二次归纳；webhook/secret 绝不在此出现（§三一）。
    """
    report = _REPORT.get_report_orm(db, report_id, user)  # viewer+ 及以上角色无权访问时返回 404
    ai = report.ai_summary if isinstance(report.ai_summary, dict) else {}
    brief = {
        "report_id": report.id,
        "report_no": report.report_no,
        "title": report.title,
        "status": report.status,
        "risk_level": report.risk_level,
        "pass_rate": float(report.pass_rate),
        "totals": {
            "total": report.total_cases, "passed": report.passed_cases,
            "failed": report.failed_cases, "error": report.error_cases, "skipped": report.skipped_cases,
        },
        "duration_ms": report.duration_ms,
        "ai_summary": ai or None,
        "test_run_id": report.test_run_id,
        # 安全摘要只有计数与标题（无 evidence / 无响应体），可安全进提示词与前端卡片。
        "security_summary": (report.summary or {}).get("security"),
    }
    return sanitize_context(brief)
