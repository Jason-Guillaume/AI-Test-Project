"""NotificationSenderNode：人工确认后触发飞书通知（§三二 不在节点写飞书 HTTP）。

- action=confirm_report → 调 notification_tool.send_report_notification（按渠道条件发送）；
- action=skip_notification → 不发送，直接 COMPLETED。

通知失败只记 NotificationRecord，**不改 TestRun / Report 状态**（§二十八 三者独立）；
节点据此把 notification_brief 写入 state 并置 COMPLETED。webhook/sign 绝不进入 state
或消息（§三一）。
"""

from __future__ import annotations

from fastapi import HTTPException

from app.agents.workflows.legacy.nodes._context import NodeContext
from app.agents.workflows.legacy.state import AgentState, set_error
from app.tools.builtin import notification_tool
from app.core.http.errors import AppError


def notification_sender_node(ctx: NodeContext, state: AgentState) -> dict:
    """发送通知并记录发送结果。"""
    action = state.get("action")
    report_id = state.get("report_id")
    project_id = state["project_id"]

    if action == "skip_notification":
        return {
            "current_stage": "COMPLETED",
            "notification_brief": {
                "skipped": True, "status": "SUCCESS", "message": "用户跳过飞书通知",
            },
        }

    if not report_id:
        return set_error(state, "EXECUTION_FAILED", "没有可发送通知的报告")

    payload = state.get("action_payload") or {}
    channel_id = payload.get("channel_id")
    try:
        result = notification_tool.send_report_notification(
            ctx.db, project_id, report_id, ctx.user, channel_id=channel_id,
        )
        return {
            "current_stage": "COMPLETED",
            "notification_record_id": result.get("record_id"),
            "notification_brief": {
                "status": result.get("status"),
                "error_message": result.get("error_message"),
                "skipped": result.get("skipped", False),
                "channel_name": result.get("channel_name"),
            },
        }
    except AppError as exc:
        return set_error(state, exc.code or "FEISHU_SEND_FAILED", exc.message)
    except HTTPException as exc:
        return set_error(state, "FEISHU_SEND_FAILED", str(exc.detail))
    except Exception as exc:  # noqa: BLE001
        return set_error(state, "FEISHU_SEND_FAILED", f"飞书通知发送失败：{exc}")
