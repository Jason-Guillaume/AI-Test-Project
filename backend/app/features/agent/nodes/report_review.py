"""ReportReview 暂停标记（interrupt_before，正常流程下不执行）。

人工在此确认报告是否触发飞书通知：
- confirm_report → notification_sender（按渠道条件发送）；
- skip_notification → notification_sender（标记 COMPLETED 不发送）。

报告本身已落库（report_generator 阶段持久化），即使跳过通知，报告记录也持久存在（§十一）。
"""

from __future__ import annotations

from app.features.agent.nodes._context import NodeContext
from app.features.agent.state import AgentState


def report_review_node(ctx: NodeContext, state: AgentState) -> dict:
    """report review 暂停标记（interrupt_before，正常流程下不会被执行）。"""
    return {}
