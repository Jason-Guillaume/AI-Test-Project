"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import time
from app.features.security_testing.zap.contracts import (
    EVENT_TYPE_PROGRESS,
    EVENT_TYPE_STAGE,
    EVENT_TYPE_WARNING,
    JOB_STATUS_PASSIVE_SCANNING,
)
from app.features.security_testing.zap.stages.contracts import ScanCancelled
from app.features.security_testing.zap.stages.contracts import ScanSnapshot
from app.features.security_testing.zap.stages.contracts import ScanStageContext
from app.features.security_testing.zap.stages.contracts import ScanTimedOut
from app.features.security_testing.zap.stages.control import cancel_requested
from app.features.security_testing.zap.stages.control import checkpoint
from app.features.security_testing.zap.stages.control import effective_duration
from app.features.security_testing.zap.stages.persistence import emit
from app.features.security_testing.zap.stages.persistence import heartbeat
from app.features.security_testing.zap.stages.persistence import update_job


def stage_passive(context: ScanStageContext, snap: ScanSnapshot, started: float) -> None:
    """PASSIVE_SCANNING：被动扫描在请求产生时自动运行，这里等待队列清空。"""
    if not snap.passive_enabled:
        return
    checkpoint(context, snap, JOB_STATUS_PASSIVE_SCANNING, "等待被动扫描完成", progress=62)
    emit(context, snap, EVENT_TYPE_STAGE, JOB_STATUS_PASSIVE_SCANNING, "等待被动扫描队列清空")
    context.connector.start_passive_scan()
    deadline_polls = max(1, int(context.passive_wait / context.poll))
    for tick in range(deadline_polls):
        if cancel_requested(context, snap):
            raise ScanCancelled(JOB_STATUS_PASSIVE_SCANNING)
        if time.monotonic() - started > effective_duration(context, snap):
            raise ScanTimedOut(JOB_STATUS_PASSIVE_SCANNING)
        progress = context.connector.wait_passive_scan(
            timeout_seconds=context.poll, poll_interval=context.poll,
        )
        heartbeat(context, snap, JOB_STATUS_PASSIVE_SCANNING, 62 + int(8 * tick / deadline_polls),
                        alerts=progress.alerts)
        if not progress.running:
            emit(context,
                snap, EVENT_TYPE_PROGRESS, JOB_STATUS_PASSIVE_SCANNING,
                "被动扫描队列已清空", {"alerts": progress.alerts},
            )
            update_job(context, snap, progress=70, stage=JOB_STATUS_PASSIVE_SCANNING)
            return
    emit(context,
        snap, EVENT_TYPE_WARNING, JOB_STATUS_PASSIVE_SCANNING,
        "被动扫描未在规定时间内完成，继续后续阶段",
        {"passive_wait_seconds": context.passive_wait},
    )
    update_job(context, snap, progress=70, stage=JOB_STATUS_PASSIVE_SCANNING)
