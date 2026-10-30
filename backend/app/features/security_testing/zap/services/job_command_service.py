"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.platform.projects.services.access_service import get_project_or_404

from sqlalchemy.orm import Session
from app.features.security_testing.zap.contracts import (
    JOB_STATUS_CANCELLED,
    JOB_STATUS_PENDING,
    JOB_TERMINAL_STATUSES,
)
from app.features.security_testing.zap.models.job import SecurityScanJob
from app.features.security_testing.zap.services import _access
from app.core.models.identity import User
from app.core.http.errors import AppError
from app.features.security_testing.zap.services.job_access import emit_job_event
from app.features.security_testing.zap.services.job_access import load_job
from app.features.security_testing.zap.services.job_access import utcnow


def cancel(db: Session, project_id: int, user: User, job_id: int) -> SecurityScanJob:
    """请求取消：只置位 cancel_requested，由 Worker 在下一个检查点真正停止。"""
    project = get_project_or_404(db, project_id, user)
    row = load_job(db, project_id, job_id)
    if row.status in JOB_TERMINAL_STATUSES:
        raise AppError("该任务已结束，无法取消", status_code=409)
    _access.require_member(db, project, user)

    row.cancel_requested = True
    if row.status == JOB_STATUS_PENDING:
        # 还没被领取的任务直接判为取消，不必等 Worker 唤醒。
        row.status = JOB_STATUS_CANCELLED
        row.stage = "已取消"
        row.finished_at = utcnow()
        row.error_message = "任务尚未开始即被取消"
        emit_job_event(db, row.id, row.project_id, "STAGE", JOB_STATUS_CANCELLED, "任务尚未开始即被取消")
    else:
        emit_job_event(db, row.id, row.project_id, "STAGE", row.status, "已请求取消扫描")
    db.commit()
    db.refresh(row)
    return row
