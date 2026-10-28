"""持久化知识文档解析调度器。

工作线程只领取数据库队列中的作业；解析状态、失败原因与分块均落库，
应用重启后会重新领取尚未完成或租约过期的作业。
"""

from __future__ import annotations

import logging
import threading
import time

from sqlalchemy.orm import Session

from app.features.knowledge.services.knowledge_service import KnowledgeService
from app.shared.database import SessionLocal

log = logging.getLogger(__name__)


class KnowledgeParseWorker:
    """单实例轮询解析队列；多进程通过行锁安全领取不同作业。"""

    def __init__(self, db_factory=SessionLocal, poll_seconds: float = 1.5) -> None:
        """保存数据库会话工厂与空闲轮询间隔。"""
        self._db_factory = db_factory
        self._poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._service = KnowledgeService()

    def start(self) -> None:
        """启动后台解析线程；重复调用不会创建重复线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="knowledge-parse-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """请求 Worker 停止并等待当前解析边界结束。"""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        self._thread = None

    def _loop(self) -> None:
        """持续领取作业；解析异常已由服务记录，线程保持可用。"""
        while not self._stop.is_set():
            db: Session = self._db_factory()
            try:
                handled = self._service.process_one_parse_job(db)
            except Exception:  # noqa: BLE001 — 单个队列错误不能终止工作线程。
                db.rollback()
                log.exception("知识文档解析队列发生未处理异常")
                handled = False
            finally:
                db.close()
            if not handled:
                self._stop.wait(self._poll_seconds)
