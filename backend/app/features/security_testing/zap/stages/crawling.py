"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.security_testing.zap import scope_guard
from app.features.security_testing.zap.connector import ZAPConnectorError
from app.features.security_testing.zap.contracts import (
    EVENT_TYPE_PROGRESS,
    EVENT_TYPE_STAGE,
    EVENT_TYPE_WARNING,
    JOB_STATUS_CRAWLING,
    WEB_CRAWL_MODES,
)
from app.features.security_testing.zap.stages.contracts import ScanSnapshot
from app.features.security_testing.zap.stages.contracts import ScanStageContext
from app.features.security_testing.zap.stages.control import checkpoint
from app.features.security_testing.zap.stages.persistence import emit
from app.features.security_testing.zap.stages.control import fail
from app.features.security_testing.zap.stages.persistence import update_job
from app.features.security_testing.zap.stages.control import wait_scans


def stage_crawling(context: ScanStageContext, snap: ScanSnapshot, started: float, scan_refs: list[str]) -> None:
    """CRAWLING：Client Spider 优先，失败或不可用时退回传统 Spider。"""
    if snap.scan_mode not in WEB_CRAWL_MODES:
        return
    checkpoint(context, snap, JOB_STATUS_CRAWLING, "爬取页面与 API", progress=20)
    emit(context, snap, EVENT_TYPE_STAGE, JOB_STATUS_CRAWLING, "开始爬取")

    entry = snap.entry_url or snap.base_url
    # 入口地址是 ZAP 真正会访问的第一个地址：在发出任何爬虫请求之前再校验一次，
    # 避免创建到执行之间配置变化把范围悄悄扩大（§三十四 第 1 条）。
    scope_guard.assert_redirect_allowed(
        entry, base_url=snap.base_url, allowed_hosts=snap.allowed_hosts or None,
    )
    refs: list[str] = []
    crawler_kind = ""
    if snap.client_spider_enabled:
        try:
            refs.append(context.connector.start_client_spider(entry, max_depth=snap.max_depth)["scan_ref"])
            crawler_kind = "client_spider"
        except ZAPConnectorError as exc:
            if exc.reason in ("ZAP_PLUGIN_MISSING", "ZAP_SPIDER_FAILED"):
                emit(context,
                    snap, EVENT_TYPE_WARNING, JOB_STATUS_CRAWLING,
                    f"Client Spider 不可用，改用传统 Spider：{exc.message}",
                )
            else:
                raise
    if not refs and snap.spider_enabled:
        refs.append(context.connector.start_spider(entry, max_depth=snap.max_depth)["scan_ref"])
        crawler_kind = crawler_kind or "spider"
    if not refs:
        fail(context, snap, "SECURITY_SCAN_SPIDER_FAILED", "策略未启用任何可用爬虫，无法采集扫描对象")

    scan_refs.extend(r for r in refs if r)
    done = wait_scans(context, snap, started, scan_refs, stage=JOB_STATUS_CRAWLING,
                            base_progress=20, span=40)
    emit(context,
        snap, EVENT_TYPE_PROGRESS, JOB_STATUS_CRAWLING,
        f"爬取结束（{crawler_kind}），发现 {done.urls} 个 URL",
        {"crawler": crawler_kind, "scan_refs": scan_refs, "urls": done.urls},
    )
    update_job(context, snap, zap_scan_reference=",".join(scan_refs), urls_discovered=done.urls)
