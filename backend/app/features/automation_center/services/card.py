"""自动化结果的飞书卡片。发送仍走现有飞书传输服务。"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.security.sanitizer import sanitize_context, sanitize_text

_COLOR = {"SUCCESS": "green", "FAILED": "red", "CANCELLED": "grey", "TIMEOUT": "orange"}


def build_automation_card(
    *, project_name: str, status: str, branch: str, environment_name: str,
    total: int, passed: int, failed: int, skipped: int, broken: int,
    pass_rate: str, duration_ms: int | None, started_at: str, report_id: int | None,
    report_ready: bool,
) -> dict[str, Any]:
    """构造交互卡片。报告按钮指向需要登录的平台页面。"""
    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": (
            f"**项目**：{sanitize_text(project_name)}\n"
            f"**分支**：{sanitize_text(branch or '未记录')}\n"
            f"**环境**：{sanitize_text(environment_name or '未记录')}\n"
            f"**执行时间**：{sanitize_text(started_at or '未记录')}"
        )}},
        {"tag": "div", "fields": [
            {"is_short": True, "text": {"tag": "lark_md", "content": f"**总数**\n{total}"}},
            {"is_short": True, "text": {"tag": "lark_md", "content": f"**成功**\n{passed}"}},
            {"is_short": True, "text": {"tag": "lark_md", "content": f"**失败**\n{failed}"}},
            {"is_short": True, "text": {"tag": "lark_md", "content": f"**中断**\n{broken}"}},
            {"is_short": True, "text": {"tag": "lark_md", "content": f"**跳过**\n{skipped}"}},
            {"is_short": True, "text": {"tag": "lark_md", "content": f"**通过率**\n{pass_rate}%"}},
        ]},
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**执行耗时**：{duration_ms or 0} ms"}},
    ]
    if report_ready and report_id is not None:
        url = _report_url(report_id)
        if url:
            elements.append({"tag": "action", "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看 Allure 报告"},
                "type": "primary",
                "url": url,
            }]})
        else:
            elements.append({"tag": "note", "elements": [{
                "tag": "plain_text", "content": "报告已保存。请登录测试平台查看，当前未配置平台外部地址。",
            }]})
    else:
        elements.append({"tag": "note", "elements": [{
            "tag": "plain_text", "content": "执行已结束，Allure 报告尚未上传成功。",
        }]})
    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": sanitize_text(f"自动化测试 {status}")},
            "template": _COLOR.get(status, "blue"),
        },
        "elements": elements,
    }
    return sanitize_context(card)


def _report_url(report_id: int) -> str:
    """拼接需要登录的报告页。未配置外部地址时不放按钮。"""
    base = settings.PUBLIC_APP_BASE_URL.strip().rstrip("/")
    if not base.startswith("https://") and not base.startswith("http://"):
        return ""
    return f"{base}/console/automation-reports/{report_id}"
