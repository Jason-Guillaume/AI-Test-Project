"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.security_testing.zap.stages.contracts import ScanSnapshot

import logging
import time
from typing import Callable
from sqlalchemy.orm import Session
from app.features.security_testing.zap.connector import ZAPConnector, ZAPConnectorError
from app.features.security_testing.zap.contracts import (
    EVENT_TYPE_ERROR,
    EVENT_TYPE_WARNING,
    JOB_STATUS_CANCELLED,
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_TIMED_OUT,
)
from app.features.security_testing.zap.normalizer import ZAPAlertNormalizer
from app.core.config import settings
from app.core.database.session import SessionLocal
from app.core.http.errors import AppError
from app.features.security_testing.zap.stages.contracts import ScanCancelled
from app.features.security_testing.zap.stages.contracts import ScanStageContext
from app.features.security_testing.zap.stages.contracts import ScanTimedOut
from app.features.security_testing.zap.stages.contracts import _connector_error_code
from app.features.security_testing.zap.stages.persistence import emit
from app.features.security_testing.zap.stages.control import fail
from app.features.security_testing.zap.stages.persistence import finalize
from app.features.security_testing.zap.stages.persistence import load_snapshot
from app.features.security_testing.zap.stages.active import stage_active
from app.features.security_testing.zap.stages.authentication import stage_authenticating
from app.features.security_testing.zap.stages.crawling import stage_crawling
from app.features.security_testing.zap.stages.importing import stage_import
from app.features.security_testing.zap.stages.passive import stage_passive
from app.features.security_testing.zap.stages.preparing import stage_preparing
from app.features.security_testing.zap.stages.control import stop_scans


log = logging.getLogger(__name__)


class ScanOrchestrator:
    """唯一扫描阶段推进与资源释放入口；ScanWorker 独占队列。"""

    def __init__(
        self,
        connector: ZAPConnector,
        *,
        db_factory: Callable[[], Session] = SessionLocal,
        poll_interval_seconds: float = 3.0,
        passive_wait_seconds: float | None = None,
        max_job_duration_seconds: int | None = None,
    ) -> None:
        """初始化编排器。

        Args:
            connector: 已构造好的 ZAP 连接器（Worker 通过 client.build_connector 创建）。
            db_factory: 每个检查点新建一个 Session，长等待不占用事务。
            poll_interval_seconds: 阶段内的轮询间隔，同时是取消 / 超时的检查粒度。
            passive_wait_seconds: 单次等待被动扫描队列清空的超时。
            max_job_duration_seconds: 全局任务时长上限（默认取 ZAP_MAX_JOB_DURATION_SECONDS）。
        """
        self._connector = connector
        self._db_factory = db_factory
        self._poll = max(0.2, float(poll_interval_seconds))
        self._passive_wait = (
            float(passive_wait_seconds)
            if passive_wait_seconds is not None
            else max(5.0, float(settings.ZAP_PASSIVE_WAIT_SECONDS))
        )
        self._max_duration = int(
            max_job_duration_seconds or int(settings.ZAP_MAX_JOB_DURATION_SECONDS)
        )
        self._context = ScanStageContext(self._connector, self._db_factory, self._poll, self._passive_wait, self._max_duration)

    def run(self, job_id: int) -> str:
        """走完一个任务，返回终态字符串。"""
        snap = load_snapshot(self._context, job_id)
        if snap is None:
            log.warning("ZAP 扫描任务 %s 无法加载快照（任务或目标不存在）", job_id)
            return JOB_STATUS_FAILED
        if snap.target_id is None or not snap.base_url:
            fail(self._context, snap, "SECURITY_SCAN_TARGET_NOT_FOUND", "扫描目标不存在或未配置扫描根地址")
            return JOB_STATUS_FAILED

        started = time.monotonic()
        normalizer = ZAPAlertNormalizer(project_id=snap.project_id, target_id=snap.target_id)
        scan_refs: list[str] = []
        try:
            stage_preparing(self._context, snap, started)
            stage_authenticating(self._context, snap, started)
            stage_crawling(self._context, snap, started, scan_refs)
            stage_passive(self._context, snap, started)
            stage_active(self._context, snap, started, scan_refs)
            stage_import(self._context, snap, started, normalizer)
            # 成功路径也要落库：只把 status 赋给局部变量会让任务永远停在 IMPORTING_RESULTS。
            finalize(self._context, snap, JOB_STATUS_COMPLETED)
            status = JOB_STATUS_COMPLETED
        except ScanCancelled as exc:
            status = JOB_STATUS_CANCELLED
            emit(self._context, snap, EVENT_TYPE_WARNING, exc.stage, "扫描已按请求取消")
            finalize(self._context, snap, JOB_STATUS_CANCELLED, error_message="扫描已按请求取消")
        except ScanTimedOut as exc:
            status = JOB_STATUS_TIMED_OUT
            emit(self._context, snap, EVENT_TYPE_WARNING, exc.stage, "扫描超过最长运行时间")
            finalize(self._context,
                snap, JOB_STATUS_TIMED_OUT, error_code="SECURITY_SCAN_TIMEOUT",
                error_message="扫描超过最长运行时间",
            )
        except ZAPConnectorError as exc:
            status = JOB_STATUS_FAILED
            emit(self._context, snap, EVENT_TYPE_ERROR, snap.scan_mode, exc.message)
            finalize(self._context,
                snap, JOB_STATUS_FAILED, error_code=_connector_error_code(exc), error_message=exc.message,
            )
        except AppError as exc:
            status = JOB_STATUS_FAILED
            code = getattr(exc, "code", None) or "SECURITY_SCAN_SCOPE_VIOLATION"
            emit(self._context, snap, EVENT_TYPE_ERROR, snap.scan_mode, exc.message)
            finalize(self._context, snap, JOB_STATUS_FAILED, error_code=code, error_message=exc.message)
        except Exception as exc:  # noqa: BLE001 - 兜底：任务必须有终态
            status = JOB_STATUS_FAILED
            log.exception("ZAP 扫描任务 %s 执行出现未预期异常", job_id)
            emit(self._context, snap, EVENT_TYPE_ERROR, snap.scan_mode, "扫描执行出现未预期异常")
            finalize(self._context, snap, JOB_STATUS_FAILED, error_message="扫描执行出现未预期异常")
        finally:
            stop_scans(self._context, scan_refs)
            try:
                self._connector.close()
            except Exception:  # noqa: BLE001
                log.warning("关闭 ZAP 连接器失败", exc_info=True)
        return status


__all__ = [
    'ScanCancelled',
    'ScanTimedOut',
    'ScanSnapshot',
]
