"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlsplit
from sqlalchemy.orm import Session
from app.features.security_testing.zap.connector import ZAPConnector, ZAPConnectorError


class ScanCancelled(Exception):
    """任务被显式取消，走 CANCELLED 终态而不是 FAILED。"""


class ScanTimedOut(Exception):
    """任务超过时长上限，走 TIMED_OUT 终态。"""


@dataclass(slots=True)
class ScanSnapshot:
    """任务快照：Worker 领取后一次性读出，避免在长等待中持有 Session。"""

    job_id: int
    project_id: int
    target_id: int | None
    profile_id: int
    scan_mode: str
    test_run_id: int | None = None
    environment_id: int | None = None
    target_name: str = ""
    base_url: str = ""
    entry_url: str | None = None
    target_type: str = "API"
    environment_name: str = ""
    allowed_hosts: list[str] = field(default_factory=list)
    include_paths: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)
    authorization_status: str = ""
    active_scan_allowed: bool = False
    auth_mode: str | None = None
    profile_name: str = ""
    spider_enabled: bool = True
    client_spider_enabled: bool = False
    passive_enabled: bool = True
    active_enabled: bool = False
    max_duration: int = 30
    max_depth: int = 5
    max_concurrency: int = 4
    request_delay: int = 300
    max_alerts_per_rule: int | None = None
    max_request_budget: int | None = None
    include_paths_profile: list[str] = field(default_factory=list)
    exclude_paths_profile: list[str] = field(default_factory=list)
    selected_rule_ids: list[str] = field(default_factory=list)


def _now():
    """任务时间戳：统一用 UTC 感知不到的 naive 本地时间，与仓库其它表保持一致。"""
    from datetime import datetime

    return datetime.now()


def _host_pattern(base_url: str) -> str:
    """从扫描根地址提取 ZAP Context 用的 host 模式。"""
    from urllib.parse import urlsplit

    parts = urlsplit(base_url or "")
    netloc = parts.netloc or ""
    host = netloc.split("@")[-1].split(":")[0]
    port = ""
    if ":" in netloc and not netloc.startswith("["):
        host, _, port = netloc.partition(":")
    elif netloc.startswith("["):
        end = netloc.find("]")
        host = netloc[1:end]
        rest = netloc[end + 1:]
        if rest.startswith(":"):
            port = rest[1:]
    if port:
        return f"{host}:{port}"
    return host


def _connector_error_code(exc: ZAPConnectorError) -> str:
    """ZAP 连接器原因码 → 平台错误码。"""
    mapping = {
        "ZAP_SERVICE_UNAVAILABLE": "ZAP_SERVICE_UNAVAILABLE",
        "ZAP_API_AUTH_FAILED": "ZAP_API_AUTH_FAILED",
        "ZAP_PLUGIN_MISSING": "ZAP_PLUGIN_MISSING",
        "ZAP_VERSION_UNSUPPORTED": "ZAP_VERSION_UNSUPPORTED",
        "ZAP_CONTEXT_FAILED": "SECURITY_SCAN_CONTEXT_FAILED",
        "ZAP_SPIDER_FAILED": "SECURITY_SCAN_SPIDER_FAILED",
        "ZAP_ACTIVE_FAILED": "SECURITY_SCAN_ACTIVE_FAILED",
        "ZAP_BAD_RESPONSE": "SECURITY_SCAN_RESULT_IMPORT_FAILED",
        "SECURITY_SCAN_SCOPE_VIOLATION": "SECURITY_SCAN_SCOPE_VIOLATION",
    }
    return mapping.get(exc.reason, "SECURITY_SCAN_FAILED")


def _build_coverage(
    *,
    urls: list[str],
    pages: Any,
    alerts: Any,
    items: int,
) -> dict[str, Any]:
    """覆盖率汇总（§三十一）。

    ``coverage_summary`` 存 {"summary": {...}, "rows": [...]} 两部分：
    summary 给列表页聚合，rows 给覆盖率明细接口逐条展示。
    不新增表——覆盖信息是该次扫描的派生结果，不是需要独立生命周期的一等实体。
    """
    from app.features.security_testing.zap.contracts import (
        COVERAGE_ACTIVE_SCANNED,
        COVERAGE_PASSIVE_ANALYZED,
    )

    alert_urls = {getattr(a, "url", "") or "" for a in (alerts or [])}
    unique_urls = sorted({str(u) for u in (urls or []) if u})[:2000]
    pages_count = int(getattr(pages, "urls", 0) or 0) or len(unique_urls)
    requests_count = int(getattr(pages, "requests", 0) or 0)
    responded = min(pages_count, requests_count) if requests_count else pages_count

    rows: list[dict[str, Any]] = []
    for url in unique_urls[:500]:
        covered = url in alert_urls
        rows.append({
            "identifier": url,
            "stage": COVERAGE_ACTIVE_SCANNED if covered else COVERAGE_PASSIVE_ANALYZED,
            "passive_analyzed": True,
            "active_scanned": bool(covered),
        })
    summary = {
        "discovered": len(unique_urls),
        "responded": int(responded),
        "passive_analyzed": int(pages_count),
        "active_scanned": int(len(alert_urls)),
        "not_covered": int(max(0, len(unique_urls) - pages_count)),
    }
    return {"summary": summary, "rows": rows}


@dataclass(frozen=True)
class ScanStageContext:
    """扫描阶段的有限资源配置；不包含调度器、模型或用户回调。"""

    connector: ZAPConnector
    db_factory: Callable[[], Session]
    poll: float
    passive_wait: float
    max_duration: int
