"""ZAP 扫描后台任务（§八：禁止在 HTTP 请求里同步等待）。

设计要点：
- **队列就是数据库**。任务领取用 ``SELECT ... FOR UPDATE SKIP LOCKED``，
  多个实例并发时不会重复领取同一个任务，也不需要引入外部消息队列。
- **心跳与取消都持久化**。``heartbeat_at`` 让进程重启后能判出「谁的任务没跑完」；
  ``cancel_requested`` 是库里的一列，所以取消请求在进程重启后依然有效。
- **启动即清扫**。服务重启后，凡是在中间态且心跳超时的任务一律判为 ``TIMED_OUT``，
  绝不继续推进，也绝不谎报成功。
- **HTTP 只登记任务**。Router 调用 job_service.create 之后立即返回，
  真正的扫描由本模块的守护线程（或测试里的 tick()）驱动。

线程只从 main.py 的 lifespan 启动；Router 与测试都不该直接调 start()。
"""

from __future__ import annotations

import logging
import os
import platform
import secrets
import threading
from datetime import datetime, timedelta
from typing import Callable

from sqlalchemy.orm import Session

from app.features.security_testing.zap.client import build_connector, get_zap_state
from app.features.security_testing.zap.contracts import (
    JOB_INFLIGHT_STATUSES,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_FAILED,
    JOB_STATUS_PREPARING,
    JOB_STATUS_PENDING,
    JOB_STATUS_TIMED_OUT,
    JOB_TERMINAL_STATUSES,
)
from app.features.security_testing.zap import event_log
from app.features.security_testing.zap.models.job import SecurityScanJob
from app.features.security_testing.zap.orchestrator import ScanOrchestrator
from app.shared.config import settings
from app.shared.database import SessionLocal

log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now()


def _owner_name() -> str:
    """任务归属标识：实例（主机+pid）唯一，便于排查「任务被谁领走了」。"""
    return f"{platform.node() or 'unknown'}:{os.getpid()}:{secrets.token_hex(4)}"


class ScanWorker:
    """DB 驱动的扫描任务领取与执行。

    用法（main.py lifespan）::

        worker = ScanWorker()
        worker.start()          # 启动守护线程
        ...
        worker.stop()           # 优雅停止
    """

    def __init__(
        self,
        *,
        db_factory: Callable[[], Session] = SessionLocal,
        owner: str | None = None,
        poll_interval_seconds: float | None = None,
        max_concurrent_jobs: int | None = None,
        heartbeat_timeout_seconds: int | None = None,
        orchestrator_factory: Callable[[object], ScanOrchestrator] | None = None,
    ) -> None:
        self._db_factory = db_factory
        self._owner = owner or _owner_name()
        self._poll_interval = max(
            0.2, float(poll_interval_seconds if poll_interval_seconds is not None
                       else settings.ZAP_WORKER_POLL_INTERVAL_SECONDS)
        )
        self._max_concurrent = max(1, int(max_concurrent_jobs or settings.ZAP_MAX_CONCURRENT_JOBS or 1))
        self._heartbeat_timeout = max(
            30, int(heartbeat_timeout_seconds if heartbeat_timeout_seconds is not None
                    else settings.ZAP_HEARTBEAT_TIMEOUT_SECONDS)
        )
        self._orchestrator_factory = orchestrator_factory
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._processed = 0

    # ------------------------------------------------------------------ 生命周期

    @property
    def owner(self) -> str:
        return self._owner

    @property
    def processed_count(self) -> int:
        return self._processed

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """启动守护线程。未启用 ZAP 时不启动，避免空转与误导性日志。"""
        with self._lock:
            if self.is_running:
                return
            if not settings.ZAP_ENABLED:
                log.info("ZAP 扫描后台任务未启动：ZAP_ENABLED=false")
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._loop, name="zap-scan-worker", daemon=True)
            self._thread.start()
            log.info("ZAP 扫描后台任务已启动 owner=%s", self._owner)

    def stop(self, timeout_seconds: float = 5.0) -> None:
        """请求停止并在超时时间内等待线程退出。已领取的任务会在下一个检查点看到取消位。"""
        self._stop_event.set()
        with self._lock:
            thread = self._thread
            self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=max(0.1, timeout_seconds))
        log.info("ZAP 扫描后台任务已停止")

    def _loop(self) -> None:
        """主循环：先做一次启动清扫，然后按间隔轮询。"""
        try:
            self.tick()
        except Exception:  # noqa: BLE001 - 单轮异常不能打挂线程
            log.exception("ZAP 扫描后台任务首轮清扫失败")
        while not self._stop_event.wait(self._poll_interval):
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("ZAP 扫描后台任务轮询失败")

    # ------------------------------------------------------------------ 单轮执行

    def tick(self) -> int:
        """执行一轮：清扫超时任务 → 领取任务 → 逐个跑完。返回本轮处理的任务数。

        本方法可被测试直接调用，从而不需要真的等线程轮询。
        """
        swept = self._sweep()
        if swept:
            log.warning("ZAP 扫描后台任务清扫了 %s 个中断任务", swept)

        handled = 0
        if not get_zap_state().enabled:
            return handled
        for job_id in self._claimable_ids():
            if self._stop_event.is_set():
                break
            handled += self._run_job(job_id)
        self._processed += handled
        return handled

    def _claimable_ids(self) -> list[int]:
        """找出可以被本实例领取的任务 ID（并发上限内）。"""
        db = self._db_factory()
        try:
            inflight = (
                db.query(SecurityScanJob)
                .filter(SecurityScanJob.status.in_(JOB_INFLIGHT_STATUSES))
                .count()
            )
            if inflight >= self._max_concurrent:
                return []
            rows = (
                db.query(SecurityScanJob)
                .filter(SecurityScanJob.status == JOB_STATUS_PENDING)
                .with_for_update(skip_locked=True)
                .order_by(SecurityScanJob.id.asc())
                .limit(self._max_concurrent - inflight)
                .all()
            )
            return [row.id for row in rows]
        finally:
            db.close()

    def _claim(self, job_id: int) -> SecurityScanJob | None:
        """把任务标记为「本实例正在执行」。抢不到就返回 None。"""
        db = self._db_factory()
        try:
            row = (
                db.query(SecurityScanJob)
                .filter(SecurityScanJob.id == job_id, SecurityScanJob.status == JOB_STATUS_PENDING)
                .with_for_update(skip_locked=True)
                .first()
            )
            if row is None:
                return None
            if row.cancel_requested:
                # 被取消的任务直接终态，不浪费一次扫描。
                row.status = JOB_STATUS_CANCELLED
                row.stage = "已取消"
                row.finished_at = _now()
                row.error_message = "任务尚未开始即被取消"
                self._emit(db, row, "STAGE", JOB_STATUS_CANCELLED, "任务尚未开始即被取消")
                db.commit()
                return None
            row.status = JOB_STATUS_PREPARING
            row.progress = 1
            row.stage = "初始化扫描上下文"
            row.started_at = row.started_at or _now()
            row.started_by_worker_at = _now()
            row.worker_owner = self._owner
            row.heartbeat_at = _now()
            row.poll_count = 0
            self._emit(db, row, "STAGE", JOB_STATUS_PREPARING, f"任务已被后台实例 {self._owner} 领取")
            db.commit()
            return row
        finally:
            db.close()

    def _run_job(self, job_id: int) -> int:
        """领取并执行一个任务，返回处理了几个任务。"""
        claimed = self._claim(job_id)
        if claimed is None:
            return 0
        if not settings.ZAP_ENABLED:
            self._finalize(job_id, JOB_STATUS_FAILED, "ZAP_WORKER_DISABLED", "ZAP 服务未启用")
            return 1
        try:
            connector = build_connector()
        except Exception as exc:  # noqa: BLE001 - 配置错误不能反复重试打挂线程
            self._finalize(job_id, JOB_STATUS_FAILED, "ZAP_SERVICE_UNAVAILABLE",
                           f"ZAP 连接构造失败：{type(exc).__name__}")
            return 1
        orchestrator = (
            self._orchestrator_factory(connector) if self._orchestrator_factory else ScanOrchestrator(connector)
        )
        try:
            terminal = orchestrator.run(job_id)
        except Exception as exc:  # noqa: BLE001 - 兜底：不能因为一次异常让整个任务卡在中间态
            log.exception("ZAP 扫描任务 %s 执行异常", job_id)
            self._finalize(job_id, JOB_STATUS_FAILED, "SECURITY_SCAN_FAILED",
                           f"扫描执行出现未预期异常：{type(exc).__name__}")
            return 1
        if terminal not in JOB_TERMINAL_STATUSES:
            self._finalize(job_id, JOB_STATUS_FAILED, "SECURITY_SCAN_FAILED", "扫描未给出终态")
        return 1

    # ------------------------------------------------------------------ 清扫与收尾

    def _sweep(self) -> int:
        """把心跳超时的中间态任务判为 TIMED_OUT，避免进程重启后任务永远卡在中间态。"""
        cutoff = _now() - timedelta(seconds=self._heartbeat_timeout)
        db = self._db_factory()
        try:
            rows = (
                db.query(SecurityScanJob)
                .filter(SecurityScanJob.status.in_(JOB_INFLIGHT_STATUSES))
                .filter(
                    # 领取成功即写 heartbeat_at；为空说明进程在领取后、写心跳前挂掉了。
                    (SecurityScanJob.heartbeat_at.is_(None)) | (SecurityScanJob.heartbeat_at < cutoff)
                )
                .with_for_update()
                .all()
            )
            count = 0
            for row in rows:
                row.status = JOB_STATUS_TIMED_OUT
                row.stage = "后台任务中断"
                row.finished_at = _now()
                row.error_code = "SECURITY_SCAN_TIMEOUT"
                row.error_message = (
                    f"执行该任务的后台实例已无心跳（owner={row.worker_owner}），任务已判为超时"
                )
                self._emit(db, row, "STAGE", JOB_STATUS_TIMED_OUT, "后台实例心跳超时，任务已判为超时")
                count += 1
            if count:
                db.commit()
            return count
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("ZAP 扫描后台任务清扫失败")
            return 0
        finally:
            db.close()

    def _finalize(
        self,
        job_id: int,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """把一个任务推到给定终态；只在任务仍在中间态时写入。"""
        db = self._db_factory()
        try:
            row = (
                db.query(SecurityScanJob)
                .filter(SecurityScanJob.id == job_id)
                .with_for_update()
                .first()
            )
            if row is None or row.status in JOB_TERMINAL_STATUSES:
                return
            row.status = status
            row.stage = {"FAILED": "执行失败", "TIMED_OUT": "执行超时", "CANCELLED": "已取消"}.get(
                status, "已结束"
            )
            row.finished_at = _now()
            if error_code:
                row.error_code = error_code
            if error_message:
                row.error_message = error_message
            self._emit(db, row, "STAGE", status, error_message or f"任务已结束（{status}）")
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
            log.exception("ZAP 扫描任务 %s 收尾失败", job_id)
        finally:
            db.close()

    @staticmethod
    def _emit(db: Session, row: SecurityScanJob, event_type: str, stage: str, message: str) -> None:
        """写一条过程事件；seq 分配与并发冲突重试统一在 event_log。"""
        event_log.add_event(
            db,
            job_id=row.id,
            project_id=row.project_id,
            event_type=event_type,
            stage=stage,
            message=str(message),
        )


def create_worker(**kwargs) -> ScanWorker:
    """工厂函数，便于测试注入依赖。"""
    return ScanWorker(**kwargs)
