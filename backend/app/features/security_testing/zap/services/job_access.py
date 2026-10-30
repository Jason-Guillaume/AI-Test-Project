"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session
from app.features.security_testing.zap import event_log
from app.features.security_testing.zap.models.job import SecurityScanJob
from app.features.security_testing.zap.models.profile import SecurityScanProfile
from app.features.security_testing.zap.models.target import SecurityScanTarget
from app.features.security_testing.zap.services import _access, profile_service, target_service
from app.platform.environment_configuration.services.environment_service import resolve_project_environment
from app.features.test_management.models.execution import TestRun
from app.core.models.configuration import Environment
from app.core.http.errors import (
    CODE_NOT_FOUND,
    CODE_SECURITY_SCAN_AUTH_PROFILE_NOT_FOUND,
    CODE_SECURITY_SCAN_NOT_AUTHORIZED,
    CODE_SECURITY_SCAN_PROFILE_NOT_FOUND,
    AppError,
)


_PROFILE_NOT_FOUND = AppError(
    "扫描策略不存在", status_code=404, code=CODE_SECURITY_SCAN_PROFILE_NOT_FOUND
)


_AUTH_PROFILE_NOT_FOUND = AppError(
    "认证配置不存在", status_code=404, code=CODE_SECURITY_SCAN_AUTH_PROFILE_NOT_FOUND
)


def load_job(db: Session, project_id: int, job_id: int) -> SecurityScanJob:
    """按 ID 读任务；跨项目一律 404，不暴露是否存在（红线 1）。"""
    row = (
        db.query(SecurityScanJob)
        .filter(SecurityScanJob.id == job_id, SecurityScanJob.project_id == project_id)
        .first()
    )
    if row is None:
        raise _access.job_not_found()
    return row


def load_target(db: Session, project_id: int, target_id: int) -> SecurityScanTarget:
    """按 ID 读扫描目标；跨项目一律 404。"""
    row = target_service.get_or_none(db, project_id, target_id)
    if row is None:
        raise _access.target_forbidden()
    return row


def load_profile(db: Session, project_id: int, profile_id: int) -> SecurityScanProfile:
    """按 ID 读扫描策略；内置策略（project_id 为空）对所有项目可见。"""
    row = profile_service.get_or_none(db, project_id, profile_id)
    if row is None:
        raise _PROFILE_NOT_FOUND
    return row


def check_test_run(db: Session, project_id: int, test_run_id: int | None) -> None:
    """校验关联的测试执行记录是否属于本项目。

    不校验的话，ZAP 打出的 Finding 会以本项目的 project_id 挂到别的项目执行记录上，
    再经报告层（只按 test_run_id 过滤）回流出去。跨资源越权按 404 处理，不暴露存在性。
    """
    if not test_run_id:
        return
    row = db.get(TestRun, test_run_id)
    if row is None or row.project_id != project_id:
        raise AppError("关联的测试执行记录不存在", status_code=404, code=CODE_NOT_FOUND)


def resolve_environment(db: Session, project_id: int, environment_id: int | None) -> Environment | None:
    """读取项目绑定的环境配置；空 ID 返回 None。"""
    if not environment_id:
        return None
    return resolve_project_environment(db, project_id, environment_id)


def utcnow() -> datetime:
    """与仓库其它表一致的时间戳。"""
    return datetime.now()


def emit_job_event(
    db: Session,
    job_id: int,
    project_id: int,
    event_type: str,
    stage: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """写一条过程事件；seq 分配与并发冲突重试统一在 event_log。只 add，提交由调用方负责。"""
    event_log.add_event(
        db,
        job_id=job_id,
        project_id=project_id,
        event_type=event_type,
        stage=stage,
        message=message,
        payload=payload,
    )


def merge_paths(*groups: list[str]) -> list[str]:
    """合并多组路径清单，去重并保序。"""
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def job_not_authorized(message: str) -> AppError:
    """主动扫描缺少人类批准：返回 403，让前端明确显示授权不足。"""
    return AppError(message, status_code=403, code=CODE_SECURITY_SCAN_NOT_AUTHORIZED)
