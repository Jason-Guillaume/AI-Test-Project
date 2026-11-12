"""报告投递应用用例，协调报告访问、项目权限、渠道规则与通知传输。"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.http.errors import not_found
from app.core.http.pagination import DEFAULT_PAGE_SIZE
from app.core.models.identity import User
from app.features.reports.services import ReportService
from app.platform.notifications.models.channel import NotificationChannel
from app.platform.notifications.models.notification_record import NotificationRecord
from app.platform.notifications.schemas_channel import NotificationRecordListResponse
from app.platform.notifications.services import ChannelService, FeishuNotificationService
from app.platform.projects.services.access_service import require_writable_project
from app.orchestration.report_delivery.card_builder import build_report_card, should_notify


class ReportDeliveryService:
    """统一协调 REST 与 Agent 工具共用的报告投递流程。"""

    def __init__(self) -> None:
        self._reports = ReportService()
        self._channels = ChannelService()
        self._transport = FeishuNotificationService()

    def deliver(
        self,
        db: Session,
        project_id: int | None,
        report_id: int,
        user: User,
        *,
        channel_id: int | None = None,
    ) -> tuple[NotificationRecord | None, NotificationChannel | None]:
        """发送报告；返回空记录表示因无渠道、禁用或通知条件而跳过。"""
        report = self._reports.get_report_orm(db, report_id, user)
        require_writable_project(db, report.project_id, user)
        if project_id is not None and report.project_id != project_id:
            raise not_found("测试报告不存在")

        channel = self._channels.resolve_channel(
            db, report.project_id, user, channel_id=channel_id,
        )
        if channel is None or not channel.enabled:
            return None, channel

        condition = (channel.config_json or {}).get("notify_condition", "ALWAYS")
        if not should_notify(condition, report):
            return None, channel

        card = build_report_card(report)
        record = self._transport.send_card(
            db, channel, report.id, card, actor_id=user.id,
        )
        return record, channel

    def list_records(
        self,
        db: Session,
        report_id: int,
        user: User,
        *,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> NotificationRecordListResponse:
        """校验报告可见性后列出对应通知审计记录。"""
        report = self._reports.get_report_orm(db, report_id, user)
        return self._channels.list_records_for_report(
            db, report.project_id, report.id, page=page, page_size=page_size,
        )
