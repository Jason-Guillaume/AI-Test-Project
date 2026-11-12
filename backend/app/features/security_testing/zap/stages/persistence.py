"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from app.features.test_management.models.execution import TestRun
from app.features.security_testing.zap import event_log
from app.features.security_testing.zap.contracts import EVENT_TYPE_STAGE
from app.features.security_testing.zap.models.auth_profile import SecurityScanAuthProfile
from app.features.security_testing.zap.models.job import SecurityScanJob
from app.features.security_testing.zap.models.profile import SecurityScanProfile
from app.features.security_testing.zap.models.target import SecurityScanTarget
from app.features.security_testing.zap.services import auth_profile_service
from app.features.security_testing.zap.stages.contracts import ScanSnapshot
from app.features.security_testing.zap.stages.contracts import ScanStageContext
from app.features.security_testing.zap.stages.contracts import _now


def load_snapshot(context: ScanStageContext, job_id: int) -> ScanSnapshot | None:
    """一次性读出任务、目标、策略、认证配置与环境。"""
    with context.db_factory() as db:
        job = db.get(SecurityScanJob, job_id)
        if job is None:
            return None
        target = db.get(SecurityScanTarget, job.target_id) if job.target_id else None
        profile = db.get(SecurityScanProfile, job.scan_profile_id)
        if target is None or profile is None:
            return None
        auth: SecurityScanAuthProfile | None = None
        if profile.authentication_profile_id:
            auth = auth_profile_service.get_or_none(db, job.project_id, profile.authentication_profile_id)
        environment_name = ""
        if job.environment_id:
            env_row = db.get(environment_model(), job.environment_id)
            environment_name = str(getattr(env_row, "name", "") or "")
        # 兜底防线：创建时的归属校验被绕过（直接改库、历史数据）时，
        # 不把 ZAP Finding 挂到别的项目执行记录上。
        test_run_id = job.test_run_id
        if test_run_id is not None:
            run_row = db.get(TestRun, test_run_id)
            if run_row is None or run_row.project_id != job.project_id:
                test_run_id = None
        return ScanSnapshot(
            job_id=job.id,
            project_id=job.project_id,
            target_id=target.id,
            profile_id=profile.id,
            scan_mode=job.scan_mode,
            test_run_id=test_run_id,
            environment_id=job.environment_id,
            target_name=target.name,
            base_url=target.base_url,
            entry_url=target.entry_url,
            target_type=target.target_type,
            environment_name=environment_name,
            allowed_hosts=list(target.allowed_hosts or []),
            include_paths=list(target.include_paths or []),
            exclude_paths=list(target.exclude_paths or []),
            authorization_status=str(target.authorization_status or ""),
            active_scan_allowed=bool(target.active_scan_allowed),
            auth_mode=auth.auth_mode if auth else None,
            profile_name=profile.name,
            spider_enabled=bool(profile.spider_enabled),
            client_spider_enabled=bool(profile.client_spider_enabled),
            passive_enabled=bool(profile.passive_enabled),
            active_enabled=bool(profile.active_enabled),
            max_duration=int(profile.max_duration or 30),
            max_depth=int(profile.max_depth or 5),
            max_concurrency=int(profile.max_concurrency or 4),
            request_delay=int(profile.request_delay or 300),
            max_alerts_per_rule=profile.max_alerts_per_rule,
            max_request_budget=profile.max_request_budget,
            include_paths_profile=list(profile.include_paths or []),
            exclude_paths_profile=list(profile.exclude_paths or []),
            selected_rule_ids=list(profile.selected_rule_ids or []),
        )


def environment_model() -> type:
    """延迟导入环境模型，避免 Worker 在无环境表的项目里循环依赖。"""
    from app.core.models.configuration import Environment

    return Environment


def heartbeat(context: ScanStageContext, snap: ScanSnapshot, stage: str, progress: int, *, urls: int=0, requests: int=0, alerts: int=0) -> None:
    """刷新心跳与进度；不写事件，保持调用频率可控。"""
    with context.db_factory() as db:
        row = db.get(SecurityScanJob, snap.job_id)
        if row is None:
            return
        row.status = stage
        row.stage = stage
        row.progress = int(progress)
        row.heartbeat_at = _now()
        row.poll_count = int(row.poll_count or 0) + 1
        if urls:
            row.urls_discovered = int(urls)
        if requests:
            row.requests_made = int(requests)
        if alerts:
            row.total_alerts = int(alerts)
        db.commit()


def update_job(context: ScanStageContext, snap: ScanSnapshot, **fields: Any) -> None:
    """更新任务字段的通用入口。"""
    with context.db_factory() as db:
        row = db.get(SecurityScanJob, snap.job_id)
        if row is None:
            return
        for key, value in fields.items():
            setattr(row, key, value)
        db.commit()


def load_auth_profile(context: ScanStageContext, snap: ScanSnapshot) -> SecurityScanAuthProfile | None:
    """加载认证配置档案。"""
    with context.db_factory() as db:
        row = db.get(SecurityScanProfile, snap.profile_id)
        if row is None or not row.authentication_profile_id:
            return None
        return auth_profile_service.get_or_none(db, snap.project_id, row.authentication_profile_id)


def emit(context: ScanStageContext, snap: ScanSnapshot, event_type: str, stage: str, message: str, payload: dict[str, Any] | None=None) -> None:
    """发送事件对应数据。"""
    with context.db_factory() as db:
        emit_db(db, snap, event_type, stage, message, payload)


def emit_db(db: Session, snap: ScanSnapshot, event_type: str, stage: str, message: str, payload: dict[str, Any] | None=None) -> None:
    """写一条过程事件；payload 必须先脱敏，seq 分配与并发重试统一在 event_log。"""
    event_log.add_event(
        db,
        job_id=snap.job_id,
        project_id=snap.project_id,
        event_type=event_type,
        stage=stage,
        message=str(message or ""),
        payload=payload,
    )


def finalize(context: ScanStageContext, snap: ScanSnapshot, status: str, *, error_code: str | None=None, error_message: str | None=None) -> None:
    """写终态与耗时。"""
    with context.db_factory() as db:
        row = db.get(SecurityScanJob, snap.job_id)
        if row is None:
            return
        row.status = status
        row.finished_at = _now()
        if row.started_at is not None:
            row.duration_ms = int((_now() - row.started_at).total_seconds() * 1000)
        if error_code:
            row.error_code = error_code
        if error_message:
            row.error_message = str(error_message)[:500]
        db.commit()
    emit(context, snap, EVENT_TYPE_STAGE, status, f"任务结束：{status}")
