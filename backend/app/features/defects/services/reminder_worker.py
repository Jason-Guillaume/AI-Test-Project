"""缺陷积压提醒 Worker：按项目订阅汇总长期待确认/待验证记录。

每日扫描启用提醒的项目，向项目成员（member+）发送一条汇总站内通知，
detail 携带队列入口参数，前端可直接链接相应队列。

去重按「项目 + 收件人 + 提醒类型 + 业务日」持久化，业务日统一按北京时间
（UTC+8）计算；去重记录与站内通知在同一事务（子事务）内提交，失败一起回滚，
下一轮扫描可以重新发送。同项目的并发扫描通过锁项目开关行串行化。
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database.session import engine
from app.core.models.project import Project, ProjectMember
from app.core.notifications.notify import notify
from app.features.defects.models.bug import Bug
from app.features.defects.models.project_setting import DefectProjectSetting
from app.features.defects.models.reminder_dispatch import DefectReminderDispatch
from app.core.security.roles import PROJECT_ROLE_MEMBER, PROJECT_ROLE_RANKS

logger = logging.getLogger(__name__)

# 业务日时区：产品按北京时间切日，即使服务器运行在 UTC 也不会把提醒算到前一天。
BUSINESS_TIMEZONE = timezone(timedelta(hours=8))
REMINDER_TYPE_STALE_BACKLOG = "STALE_BACKLOG"


class _DuplicateDispatch(Exception):
    """同一业务日已经发送过；只回滚当前收件人的子事务，不视为扫描失败。"""


def business_date_for(now: datetime | None) -> date:
    """把扫描时间换算成北京时间业务日；裸时间按北京时间墙钟解释。"""
    reference = now or datetime.now(BUSINESS_TIMEZONE)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=BUSINESS_TIMEZONE)
    return reference.astimezone(BUSINESS_TIMEZONE).date()


def _naive_business_time(now: datetime | None) -> datetime:
    """转成可和数据库 timestamp without time zone 比较的北京时间裸值。"""
    reference = now or datetime.now(BUSINESS_TIMEZONE)
    if reference.tzinfo is None:
        return reference
    return reference.astimezone(BUSINESS_TIMEZONE).replace(tzinfo=None)


def _notify_recipient(
    db,
    *,
    project_id: int,
    user_id: int,
    business_day: date,
    title: str,
    body: str,
    detail: dict,
) -> bool:
    """在一个子事务里写去重记录和通知；重复投递返回 False，失败向上抛出。

    唯一索引冲突只代表「本业务日已发送」，回滚子事务后跳过；
    通知写入失败（notify 抛异常）则整个子事务回滚，去重记录不落下，
    本轮扫描失败，下一轮可以重试。
    """
    try:
        with db.begin_nested():
            dispatch = DefectReminderDispatch(
                project_id=project_id,
                recipient_id=user_id,
                reminder_type=REMINDER_TYPE_STALE_BACKLOG,
                business_date=business_day,
            )
            db.add(dispatch)
            try:
                db.flush()
            except IntegrityError as exc:
                raise _DuplicateDispatch from exc
            row = notify(
                db,
                user_id=user_id,
                event_type="defect.reminder",
                title=title,
                body=body,
                project_id=project_id,
                detail=detail,
                strict=True,
            )
            if row is not None:
                dispatch.notification_id = row.id
                db.flush()
        return True
    except _DuplicateDispatch:
        return False


def send_stale_reminders(db, *, now: datetime | None = None) -> int:
    """一轮去重扫描；返回实际发出提醒的项目数。调用方负责 commit。

    同一批数据在同一天重复执行不会重复发送；跨天会重新提醒。
    """
    business_day = business_date_for(now)
    reference = _naive_business_time(now)
    sent = 0
    subscriptions = (
        db.query(DefectProjectSetting)
        .filter(DefectProjectSetting.reminder_enabled.is_(True))
        .all()
    )
    for subscription in subscriptions:
        # 锁项目开关行，让同一项目的并发扫描排队执行；否则两个实例可能
        # 交叉插入不同收件人的唯一键，形成不必要的锁等待甚至死锁。
        setting = (
            db.query(DefectProjectSetting)
            .filter(DefectProjectSetting.project_id == subscription.project_id)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if setting is None or not setting.reminder_enabled:
            continue
        cutoff = reference - timedelta(days=setting.stale_reminder_days)
        stale = (
            db.query(Bug.status, Bug.id)
            .filter(
                Bug.project_id == setting.project_id,
                Bug.deleted_at.is_(None),
                Bug.archived_at.is_(None),
                Bug.is_draft.is_(False),
                Bug.status.in_(("待确认", "已修复")),
                Bug.updated_at <= cutoff,
            )
            .all()
        )
        if not stale:
            continue
        pending_confirm = sum(1 for status, _ in stale if status == "待确认")
        pending_verify = sum(1 for status, _ in stale if status == "已修复")
        # 只提醒具备写权限的成员（member+）；项目负责人是虚拟角色，不在成员表中。
        project = db.get(Project, setting.project_id)
        role_rows = (
            db.query(ProjectMember.user_id, ProjectMember.role)
            .filter(
                ProjectMember.project_id == setting.project_id,
                ProjectMember.deleted_at.is_(None),
            )
            .all()
        )
        recipient_ids = [
            user_id for user_id, role in role_rows
            if PROJECT_ROLE_RANKS.get(role, -1) >= PROJECT_ROLE_RANKS[PROJECT_ROLE_MEMBER]
        ]
        if project is not None and project.owner_id not in recipient_ids:
            recipient_ids.append(project.owner_id)
        title = (
            f"项目缺陷积压提醒：{pending_confirm} 条待确认、{pending_verify} 条待验证"
            f"超过 {setting.stale_reminder_days} 天"
        )
        detail = {
            "project_id": setting.project_id,
            "pending_confirm": pending_confirm,
            "pending_verify": pending_verify,
            "stale_days": setting.stale_reminder_days,
            "business_date": business_day.isoformat(),
            "queues": ["pending_confirm", "pending_verify"],
        }
        project_sent = False
        for user_id in recipient_ids:
            if _notify_recipient(
                db,
                project_id=setting.project_id,
                user_id=user_id,
                business_day=business_day,
                title=title,
                body="点击通知进入对应队列处理；可在缺陷页项目设置中调整订阅。",
                detail=detail,
            ):
                project_sent = True
        if project_sent:
            sent += 1
    return sent


class DefectReminderWorker:
    """每日汇总提醒守护线程，接口与分享归档 Worker 对齐。"""

    def __init__(self, *, session_factory=None) -> None:
        self._session_factory = session_factory or sessionmaker(
            bind=engine, autoflush=False, expire_on_commit=False
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.consecutive_failures = 0
        self.total_projects_notified = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="defect-reminder", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._thread = None

    def run_once(self) -> int:
        try:
            with self._session_factory() as db:
                sent = send_stale_reminders(db)
                db.commit()
            self.last_error = None
            self.consecutive_failures = 0
            self.total_projects_notified += sent
            return sent
        except Exception as exc:  # noqa: BLE001 - 定时任务记录原因并留待下轮重试
            self.consecutive_failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception("缺陷积压提醒失败（连续第 %s 次）", self.consecutive_failures)
            return 0

    def _next_delay_seconds(self) -> float:
        base = float(max(60, int(settings.DEFECT_REMINDER_INTERVAL_SECONDS)))
        if self.consecutive_failures <= 0:
            return base
        return min(base, float(60 * (2 ** min(self.consecutive_failures - 1, 5))))

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            if self._stop.wait(self._next_delay_seconds()):
                break


defect_reminder_worker = DefectReminderWorker()