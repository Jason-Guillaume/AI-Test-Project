"""自动化中心 CI 运行状态轮询。

这是回调丢失时的兜底，不进入 Agent 或统一任务调度器。
"""

from __future__ import annotations

import logging
import threading

from app.core.config import settings
from app.core.database.session import SessionLocal
from app.features.automation_center.services.center_service import AutomationCenterService

logger = logging.getLogger(__name__)


class AutomationPoller:
    """按固定间隔同步运行中的外部 CI 执行。"""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._service = AutomationCenterService()

    def start(self) -> None:
        """在独立守护线程中启动轮询。测试环境可以关闭。"""
        if not settings.AUTOMATION_POLL_ENABLED or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="automation-poller", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """通知轮询线程退出并等待一小段时间。"""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _loop(self) -> None:
        """循环同步。单轮异常只记日志，不让线程退出。"""
        while not self._stop.is_set():
            db = SessionLocal()
            try:
                self._service.poll(db)
            except Exception:  # noqa: BLE001 — 轮询失败不能拖垮应用。
                logger.exception("自动化状态轮询失败")
                db.rollback()
            finally:
                db.close()
            self._stop.wait(max(5.0, settings.AUTOMATION_POLL_SECONDS))
