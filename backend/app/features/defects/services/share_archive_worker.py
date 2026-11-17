"""过期缺陷分享的每日定时自动归档后台任务。

职责：
1. 定期幂等扫描超过 expires_at 且未归档的 DefectShareLink，标记 archived_at；
2. 保留原始分享与审计/投递记录，仅禁止继续访问；
3. 记录归档失败原因（last_error）并按退避周期重试，不因单次异常退出。
"""

from __future__ import annotations

import logging
import threading

from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database.session import engine
from app.features.defects.services.share_service import archive_expired_shares

logger = logging.getLogger(__name__)


class DefectShareArchiveWorker:
    """每日扫描并归档过期分享的守护线程 Worker，接口与现有后台 Worker 对齐。"""

    def __init__(self, *, session_factory=None) -> None:
        self._session_factory = session_factory or sessionmaker(
            bind=engine, autoflush=False, expire_on_commit=False
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.consecutive_failures: int = 0
        self.total_archived: int = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name="defect-share-archive", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def run_once(self) -> int:
        """执行一轮幂等批量归档。发生异常时记录失败原因并回滚，供后续重试。"""
        archived_total = 0
        try:
            with self._session_factory() as db:
                while not self._stop.is_set():
                    batch = archive_expired_shares(db, batch_size=500)
                    archived_total += batch
                    if batch < 500:
                        break
            self.last_error = None
            self.consecutive_failures = 0
            self.total_archived += archived_total
            if archived_total > 0:
                logger.info("已自动归档 %s 条过期缺陷分享链接", archived_total)
            return archived_total
        except Exception as exc:  # noqa: BLE001 - 定时任务记录原因并留待下轮重试
            self.consecutive_failures += 1
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.exception(
                "过期缺陷分享自动归档失败（连续第 %s 次，将在退避后重试）",
                self.consecutive_failures,
            )
            return 0

    def _next_delay_seconds(self) -> float:
        base = float(max(60, int(settings.DEFECT_SHARE_ARCHIVE_INTERVAL_SECONDS)))
        if self.consecutive_failures <= 0:
            return base
        retry_delay = float(60 * (2 ** min(self.consecutive_failures - 1, 5)))
        return min(base, retry_delay)

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            self.run_once()
            if self._stop.wait(self._next_delay_seconds()):
                break


defect_share_archive_worker = DefectShareArchiveWorker()
