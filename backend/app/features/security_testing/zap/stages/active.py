"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.security_testing.zap import scope_guard
from app.features.security_testing.zap.contracts import (
    EVENT_TYPE_PROGRESS,
    EVENT_TYPE_STAGE,
    JOB_STATUS_ACTIVE_SCANNING,
    is_active_scan,
)
from app.features.security_testing.zap.stages.contracts import ScanCancelled
from app.features.security_testing.zap.stages.contracts import ScanSnapshot
from app.features.security_testing.zap.stages.contracts import ScanStageContext
from app.features.security_testing.zap.stages.control import cancel_requested
from app.features.security_testing.zap.stages.control import checkpoint
from app.features.security_testing.zap.stages.persistence import emit
from app.features.security_testing.zap.stages.control import merged_paths
from app.features.security_testing.zap.stages.persistence import update_job
from app.features.security_testing.zap.stages.control import wait_scans


def stage_active(context: ScanStageContext, snap: ScanSnapshot, started: float, scan_refs: list[str]) -> None:
    """ACTIVE_SCANNING：受控主动扫描；未授权或非主动模式直接跳过。"""
    if not is_active_scan(snap.scan_mode) or not snap.active_enabled:
        return
    checkpoint(context, snap, JOB_STATUS_ACTIVE_SCANNING, "执行受控主动扫描", progress=74)
    emit(context, snap, EVENT_TYPE_STAGE, JOB_STATUS_ACTIVE_SCANNING, "开始主动扫描（低强度）")

    # 范围与危险路径排除必须在发出任何扫描请求之前生效（§十五）。
    # 排除清单为空时退回到内置高危路径清单，绝不因为「用户没填」就扫 logout / delete / payment。
    exclude = merged_paths(snap.exclude_paths, snap.exclude_paths_profile) or list(
        scope_guard.HIGH_RISK_ACTIVE_PATH_PATTERNS,
    )
    scan_id = context.connector.start_active_scan(
        snap.base_url,
        max_duration=min(int(snap.max_duration or 20), 60),
        max_concurrency=min(int(snap.max_concurrency or 5), 20),
        request_delay_ms=snap.request_delay,
        max_alerts_per_rule=snap.max_alerts_per_rule or 20,
        selected_rule_ids=snap.selected_rule_ids,
        excluded_paths=exclude,
    )
    if scan_id:
        scan_refs.append(scan_id)
    emit(context,
        snap, EVENT_TYPE_PROGRESS, JOB_STATUS_ACTIVE_SCANNING,
        "主动扫描已启动",
        {"scan_id": scan_id, "excluded_paths": exclude, "selected_rule_ids": snap.selected_rule_ids},
    )
    if cancel_requested(context, snap):
        raise ScanCancelled(JOB_STATUS_ACTIVE_SCANNING)
    done = wait_scans(context, snap, started, scan_refs, stage=JOB_STATUS_ACTIVE_SCANNING,
                            base_progress=74, span=24)
    emit(context,
        snap, EVENT_TYPE_PROGRESS, JOB_STATUS_ACTIVE_SCANNING,
        f"主动扫描结束，累计告警 {done.alerts} 条",
        {"alerts": done.alerts, "requests": done.requests},
    )
    update_job(context, snap, progress=98, stage=JOB_STATUS_ACTIVE_SCANNING)
