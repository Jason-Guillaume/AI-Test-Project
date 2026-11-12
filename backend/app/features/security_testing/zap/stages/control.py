"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlsplit
from app.features.security_testing.zap import scope_guard
from app.features.security_testing.zap.contracts import EVENT_TYPE_STAGE, EVENT_TYPE_WARNING
from app.features.security_testing.zap.models.job import SecurityScanJob
from app.core.http.errors import AppError
from app.features.security_testing.zap.stages.contracts import ScanCancelled
from app.features.security_testing.zap.stages.contracts import ScanSnapshot
from app.features.security_testing.zap.stages.contracts import ScanStageContext
from app.features.security_testing.zap.stages.contracts import ScanTimedOut
from app.features.security_testing.zap.stages.persistence import emit
from app.features.security_testing.zap.stages.persistence import heartbeat


log = logging.getLogger(__name__)


def wait_scans(context: ScanStageContext, snap: ScanSnapshot, started: float, scan_refs: list[str], *, stage: str, base_progress: int, span: int) -> Any:
    """轮询 ZAP 直到指定 scan id 全部结束；期间检查取消与超时。"""
    tick = 0
    max_ticks = max(1, int(context.max_duration / context.poll))
    while tick < max_ticks:
        if cancel_requested(context, snap):
            raise ScanCancelled(stage)
        if time.monotonic() - started > effective_duration(context, snap):
            raise ScanTimedOut(stage)
        progress = context.connector.get_scan_progress(scan_refs)
        tick += 1
        percent = base_progress + int(span * min(1.0, tick / max(1, max_ticks)))
        heartbeat(context, snap, stage, min(percent, base_progress + span - 1),
                        urls=progress.urls, requests=progress.requests, alerts=progress.alerts)
        if not progress.running:
            return progress
        time.sleep(context.poll)
    emit(context, snap, EVENT_TYPE_WARNING, stage, "轮询达到上限，进入下一阶段")
    return context.connector.get_scan_progress(scan_refs)


def checkpoint(context: ScanStageContext, snap: ScanSnapshot, stage: str, message: str, progress: int=0) -> None:
    """进入新阶段：写状态 + 心跳 + 阶段事件。"""
    heartbeat(context, snap, stage, progress)
    emit(context, snap, EVENT_TYPE_STAGE, stage, message)


def effective_duration(context: ScanStageContext, snap: ScanSnapshot) -> float:
    """计算本次扫描允许的最长执行时长。"""
    return float(min(context.max_duration, int(snap.max_duration or 30) * 60))


def cancel_requested(context: ScanStageContext, snap: ScanSnapshot) -> bool:
    """判断扫描任务是否收到取消请求。"""
    with context.db_factory() as db:
        row = db.get(SecurityScanJob, snap.job_id)
        return bool(row.cancel_requested) if row is not None else False


def check_running(context: ScanStageContext, snap: ScanSnapshot, started: float, stage: str) -> None:
    """检查取消位与总时长：每个阶段都要守，否则取消会被静默忽略（§八）。"""
    if cancel_requested(context, snap):
        raise ScanCancelled(stage)
    if time.monotonic() - started > effective_duration(context, snap):
        raise ScanTimedOut(stage)


def split_scope(context: ScanStageContext, urls: list[str], snap: ScanSnapshot) -> tuple[list[str], list[str]]:
    """把发现到的地址分成「范围内」与「范围外」两组。

    只做主机与端口的字符串比较，不发起 DNS 查询：发现地址可能有上千条，
    逐条解析会把导入阶段拖死。范围外不等于违规（爬虫可能只是看到了链接），
    但它们不能出现在覆盖统计里。
    """
    allowed = scope_guard._normalize_host_port_set(snap.allowed_hosts or None)
    base_netloc = (urlsplit(snap.base_url or "").netloc or "").lower()
    in_scope: list[str] = []
    dropped: list[str] = []
    for raw in urls or []:
        url = str(raw or "").strip()
        if not url:
            continue
        netloc = (urlsplit(url).netloc or "").lower()
        if netloc and (
            (allowed and netloc not in allowed)
            or (not allowed and netloc != base_netloc)
        ):
            dropped.append(url)
        else:
            in_scope.append(url)
    return in_scope, dropped


def fail(context: ScanStageContext, snap: ScanSnapshot, code: str, message: str) -> None:
    """以失败终态结束任务（异常形式向上抛，由 run() 统一收尾）。"""
    raise AppError(message, status_code=400, code=code)


def merged_paths(*groups: list[str]) -> list[str]:
    """合并目标与策略上的路径清单，去重保序。"""
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            text = str(item).strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def stop_scans(context: ScanStageContext, scan_refs: list[str]) -> None:
    """尽力停止仍在跑的 ZAP 扫描；失败只记日志，不影响终态写入。"""
    refs = [r for r in scan_refs if r]
    if not refs:
        return
    try:
        context.connector.stop_scan(refs)
    except Exception as exc:  # noqa: BLE001
        log.warning("停止 ZAP 扫描失败：%s", exc)
