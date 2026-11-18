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


def _safe_md_text(value: Any, *, max_len: int = 500) -> str:
    """脱敏后转义 HTML 尖括号并限长，避免超长文本或标签注入污染飞书卡片。"""
    cleaned = sanitize_text(value) if value is not None else ""
    if not cleaned:
        return ""
    escaped = cleaned.replace("<", "&lt;").replace(">", "&gt;")
    if len(escaped) > max_len:
        return escaped[: max_len - 1] + "…"
    return escaped


def build_defect_share_card(
    items: list[dict[str, Any]],
    *,
    channel_name: str,
    pusher_name: str,
    expires_label: str,
    allow_resolve: bool,
    keyword: str | None = None,
    part: int = 1,
    parts: int = 1,
) -> dict[str, Any]:
    """构造缺陷分享卡片。正文先脱敏，按钮链接在脱敏之后写入。

    分享凭证位于 URL Fragment。若先对整张卡片做值形态脱敏，链接里的 token 会被掩掉，
    开发人员将无法打开页面。调用方发给飞书的是返回值；入库快照由飞书服务另行脱敏。
    """
    if not items:
        raise ValueError("缺陷分享卡片至少需要一条缺陷")
    title = f"缺陷分享 · {len(items)} 条"
    elements: list[dict[str, Any]] = [{
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": (
                f"**项目** {sanitize_text(items[0].get('project_name')) or '-'}\n"
                f"**推送人** {sanitize_text(pusher_name) or '-'}\n"
                f"**有效期** {sanitize_text(expires_label) or '-'}\n"
                f"**缺陷数量** {len(items)}\n"
                f"**开发提交已解决** {'允许' if allow_resolve else '不允许'}"
            ),
        },
    }]
    for item in items[:3]:
        summary = _safe_md_text(item.get("summary"), max_len=500) or "无摘要"
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"**{_safe_md_text(item.get('bug_no'), max_len=40) or '-'}** "
                    f"{_safe_md_text(item.get('title'), max_len=180) or '-'}\n"
                    f"严重度：{_safe_md_text(item.get('severity_label'), max_len=30) or '-'}　"
                    f"状态：{_safe_md_text(item.get('status'), max_len=30) or '-'}\n"
                    f"摘要：{summary}"
                ),
            },
        })
    if len(items) > 3:
        elements.append({"tag": "div", "text": {"tag": "plain_text", "content": f"另有 {len(items) - 3} 条缺陷，请打开详情页查看。"}})
    elements.append({
        "tag": "action",
        "actions": [{
            "tag": "button",
            "text": {"tag": "plain_text", "content": "查看缺陷"},
            "type": "primary",
            "url": items[0]["share_url"],
        }],
    })
    note = f"测试开发平台 · {sanitize_text(channel_name) or '飞书群'} · 卡片不含请求和响应正文"
    elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": note}]})
    # 关键词机器人要求原文出现；关键词本身是渠道配置，不能先被凭证掩码改写。
    if keyword:
        elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": str(keyword)[:30]}]})
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": "red"},
        "elements": elements,
    }
