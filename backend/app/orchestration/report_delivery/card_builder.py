"""报告通知规则与卡片构建，属于报告投递应用用例。"""

from __future__ import annotations

from typing import Any

from app.core.security.sanitizer import sanitize_context, sanitize_text
from app.features.reports.models.report import TestReport

_RISK_COLOR = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "orange", "CRITICAL": "red"}


def should_notify(condition: str, report: "TestReport") -> bool:
    """通知条件判定（§十七）。未知条件按 ALWAYS 宽松处理，避免漏报。"""
    if condition == "ALWAYS":
        return True
    if condition == "ONLY_FAILED":
        return (report.failed_cases or 0) > 0 or (report.error_cases or 0) > 0
    if condition == "ONLY_HIGH_RISK":
        return (report.risk_level or "LOW") in ("HIGH", "CRITICAL")
    return True

def build_report_card(report: "TestReport") -> dict[str, Any]:
    """构造飞书交互卡片（§二十二），内容整体经 SensitiveDataMasker。"""
    risk = report.risk_level or "LOW"
    ai = report.ai_summary if isinstance(report.ai_summary, dict) else {}
    overview = sanitize_text(str(ai.get("overview", ""))) if ai else ""
    findings = ai.get("key_findings") if ai else None
    recommendations = ai.get("recommendations") if ai else None

    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**总数**\n{report.total_cases}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**通过**\n{report.passed_cases}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**失败**\n{report.failed_cases}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**错误**\n{report.error_cases}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**跳过**\n{report.skipped_cases}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**通过率**\n{report.pass_rate}%"}},
            ],
        },
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**执行耗时**：{report.duration_ms or 0} ms"}},
    ]
    # 安全摘要（§14）：只带计数与标题，不带 Token、不带响应体——evidence 留在
    # 平台 Finding 详情页按需拉取。沿用现有报告卡片，不新增安全专用 webhook。
    security = (report.summary or {}).get("security") if isinstance(report.summary, dict) else None
    if isinstance(security, dict) and security.get("cases"):
        top_titles = [
            sanitize_text(str(item.get("title") or ""))
            for item in (security.get("top_findings") or [])[:3]
            if item.get("title")
        ]
        content = (
            f"**安全**\n{security.get('cases', 0)} 条安全用例，"
            f"{security.get('potential_issues', 0)} 条疑似问题"
            + (f"\n- " + "\n- ".join(top_titles) if top_titles else "")
        )
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": content}})
    if overview:
        elements.append({"tag": "hr"})
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**AI 总结**\n{overview}"}})
    if findings:
        text = "\n".join(f"- {sanitize_text(str(f))}" for f in list(findings)[:5])
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**主要发现**\n{text}"}})
    if recommendations:
        text = "\n".join(f"- {sanitize_text(str(r))}" for r in list(recommendations)[:5])
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**建议**\n{text}"}})
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": "接口测试平台 · 自动发送"}]})

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": sanitize_text(f"测试报告 {report.report_no}")},
            "template": _RISK_COLOR.get(risk, "grey"),
        },
        "elements": elements,
    }
    # 卡片内容整体脱敏（§二十）：字段名掩码 + 值形态掩码（webhook / 签名密钥），
    # 防止快照里残留的敏感串被 LLM 回显后发进飞书群。
    return sanitize_context(card)
