"""ZAP 公开客户端；协议能力在 protocol 包内，权限与数据库继续留在安全领域。"""

from __future__ import annotations

from app.features.security_testing.zap.protocol.common import ACTIVE_DEPTH_HARD_CAP
from app.features.security_testing.zap.protocol.common import ACTIVE_MAX_ALERTS_PER_RULE_HARD_CAP
from app.features.security_testing.zap.protocol.common import ACTIVE_MAX_CONCURRENCY_HARD_CAP
from app.features.security_testing.zap.protocol.common import ACTIVE_MAX_DURATION_HARD_CAP
from app.features.security_testing.zap.protocol.common import ACTIVE_MAX_REQUEST_DELAY_MS
from app.features.security_testing.zap.protocol.common import ACTIVE_MAX_RULE_DURATION_HARD_CAP
from app.features.security_testing.zap.protocol.common import ACTIVE_MIN_REQUEST_DELAY_MS
from app.features.security_testing.zap.protocol.common import CAP_ABOUT
from app.features.security_testing.zap.protocol.common import CAP_ACTIVE
from app.features.security_testing.zap.protocol.common import CAP_ACTIVE_LIMITS
from app.features.security_testing.zap.protocol.common import CAP_AJAX_SPIDER
from app.features.security_testing.zap.protocol.common import CAP_AUTH
from app.features.security_testing.zap.protocol.common import CAP_CLIENT_SPIDER
from app.features.security_testing.zap.protocol.common import CAP_HISTORY
from app.features.security_testing.zap.protocol.common import CAP_OPENAPI
from app.features.security_testing.zap.protocol.common import CAP_PASSIVE
from app.features.security_testing.zap.protocol.common import CAP_SCANNER_POOL
from app.features.security_testing.zap.protocol.common import CAP_SESSION
from app.features.security_testing.zap.protocol.common import CAP_SPIDER
from app.features.security_testing.zap.protocol.common import CAP_URLS
from app.features.security_testing.zap.protocol.common import MIN_SUPPORTED_VERSION_TEXT
from app.features.security_testing.zap.protocol.common import MIN_SUPPORTED_ZAP_VERSION
from app.features.security_testing.zap.protocol.common import ZAPConnectorError
from app.features.security_testing.zap.protocol.common import ZAP_REASON_ACTIVE_FAILED
from app.features.security_testing.zap.protocol.common import ZAP_REASON_API_AUTH_FAILED
from app.features.security_testing.zap.protocol.common import ZAP_REASON_BAD_RESPONSE
from app.features.security_testing.zap.protocol.common import ZAP_REASON_CONTEXT_FAILED
from app.features.security_testing.zap.protocol.common import ZAP_REASON_PLUGIN_MISSING
from app.features.security_testing.zap.protocol.common import ZAP_REASON_SCOPE_VIOLATION
from app.features.security_testing.zap.protocol.common import ZAP_REASON_SPIDER_FAILED
from app.features.security_testing.zap.protocol.common import ZAP_REASON_UNAVAILABLE
from app.features.security_testing.zap.protocol.common import ZAP_REASON_VERSION_UNSUPPORTED
from app.features.security_testing.zap.protocol.common import is_supported_version
from app.features.security_testing.zap.protocol.common import map_alert_severity
from app.features.security_testing.zap.protocol.common import parse_zap_version

from typing import Any, Iterable, Mapping
from app.features.security_testing.zap.contracts import (
    ZAPAbout,
    ZAPAlert,
    ZAPAlertCounts,
    ZAPAuthResult,
    ZAPCapabilities,
    ZAPPagesStats,
    ZAPProgress,
    ZAPScanContext,
)
from app.features.security_testing.zap.transport import ZAPTransport
from app.features.security_testing.zap.protocol.common import ZAPProtocolState
from app.features.security_testing.zap.protocol.context import apply_scope
from app.features.security_testing.zap.protocol.authentication import browser_session_established
from app.features.security_testing.zap.protocol.capabilities import check_health
from app.features.security_testing.zap.protocol.context import clean_scan_context
from app.features.security_testing.zap.protocol.transport import close
from app.features.security_testing.zap.protocol.authentication import configure_authentication
from app.features.security_testing.zap.protocol.context import create_scan_context
from app.features.security_testing.zap.protocol.results import get_alert_counts
from app.features.security_testing.zap.protocol.results import get_alerts
from app.features.security_testing.zap.protocol.capabilities import get_capabilities
from app.features.security_testing.zap.protocol.scanning import get_scan_progress
from app.features.security_testing.zap.protocol.results import get_scan_statistics
from app.features.security_testing.zap.protocol.capabilities import get_version
from app.features.security_testing.zap.protocol.importing import import_openapi
from app.features.security_testing.zap.protocol.scanning import list_passive_rules
from app.features.security_testing.zap.protocol.results import list_urls
from app.features.security_testing.zap.protocol.scanning import set_active_scan_limits
from app.features.security_testing.zap.protocol.scanning import start_active_scan
from app.features.security_testing.zap.protocol.crawling import start_client_spider
from app.features.security_testing.zap.protocol.scanning import start_passive_scan
from app.features.security_testing.zap.protocol.crawling import start_spider
from app.features.security_testing.zap.protocol.scanning import stop_scan
from app.features.security_testing.zap.protocol.authentication import verify_authentication
from app.features.security_testing.zap.protocol.scanning import wait_passive_scan


class ZAPConnector:
    """ZAP 客户端门面；协议能力共用单连接状态，扫描队列仍归 ScanWorker。"""

    def __init__(self, transport: ZAPTransport, *, timeout_seconds: float = 30.0) -> None:
        """为当前串行扫描初始化范围与能力状态，不保存明文凭据。"""
        self._state = ZAPProtocolState(transport=transport, timeout=float(timeout_seconds))


    def check_health(self) -> ZAPAbout:
        """委托规范职责入口，保留调用契约。"""
        return check_health(self._state, )

    def get_version(self) -> str:
        """委托规范职责入口，保留调用契约。"""
        return get_version(self._state, )

    def get_capabilities(self) -> ZAPCapabilities:
        """委托规范职责入口，保留调用契约。"""
        return get_capabilities(self._state, )


    def apply_scope(self, *, base_url: str, allowed_hosts: Iterable[str]=(), include_paths: Iterable[str]=(), exclude_paths: Iterable[str]=()) -> None:
        """委托规范职责入口，保留调用契约。"""
        return apply_scope(self._state, base_url=base_url, allowed_hosts=allowed_hosts, include_paths=include_paths, exclude_paths=exclude_paths)

    def create_scan_context(self, *, host_pattern: str, context_name: str | None=None) -> ZAPScanContext:
        """委托规范职责入口，保留调用契约。"""
        return create_scan_context(self._state, host_pattern=host_pattern, context_name=context_name)

    def clean_scan_context(self) -> None:
        """委托规范职责入口，保留调用契约。"""
        return clean_scan_context(self._state, )

    def configure_authentication(self, auth: Mapping[str, Any]) -> ZAPAuthResult:
        """委托规范职责入口，保留调用契约。"""
        return configure_authentication(self._state, auth)

    def verify_authentication(self) -> tuple[bool, bool]:
        """委托规范职责入口，保留调用契约。"""
        return verify_authentication(self._state, )

    def browser_session_established(self) -> tuple[bool, str]:
        """委托规范职责入口，保留调用契约。"""
        return browser_session_established(self._state, )

    def import_openapi(self, document: str, *, file_name: str='openapi.json') -> dict[str, Any]:
        """委托规范职责入口，保留调用契约。"""
        return import_openapi(self._state, document, file_name=file_name)

    def start_spider(self, url: str, *, max_depth: int=3, max_children: int=10, max_threads: int=10, exclude_patterns: Iterable[str]=()) -> dict[str, Any]:
        """委托规范职责入口，保留调用契约。"""
        return start_spider(self._state, url, max_depth=max_depth, max_children=max_children, max_threads=max_threads, exclude_patterns=exclude_patterns)

    def start_client_spider(self, url: str, *, max_depth: int=5, page_count: int=0, target_regex: str='', user_agent_script: str='') -> dict[str, Any]:
        """委托规范职责入口，保留调用契约。"""
        return start_client_spider(self._state, url, max_depth=max_depth, page_count=page_count, target_regex=target_regex, user_agent_script=user_agent_script)

    def start_passive_scan(self) -> None:
        """委托规范职责入口，保留调用契约。"""
        return start_passive_scan(self._state, )

    def wait_passive_scan(self, timeout_seconds: float=120.0, poll_interval: float=1.0) -> ZAPProgress:
        """委托规范职责入口，保留调用契约。"""
        return wait_passive_scan(self._state, timeout_seconds, poll_interval)

    def list_passive_rules(self) -> list[dict[str, str]]:
        """委托规范职责入口，保留调用契约。"""
        return list_passive_rules(self._state, )

    def start_active_scan(self, url: str, *, max_duration: int=20, max_rule_duration: int=10, max_concurrency: int=5, request_delay_ms: int=0, max_alerts_per_rule: int=20, selected_rule_ids: Iterable[str]=(), excluded_paths: Iterable[str]=(), threshold: str='default') -> str:
        """委托规范职责入口，保留调用契约。"""
        return start_active_scan(self._state, url, max_duration=max_duration, max_rule_duration=max_rule_duration, max_concurrency=max_concurrency, request_delay_ms=request_delay_ms, max_alerts_per_rule=max_alerts_per_rule, selected_rule_ids=selected_rule_ids, excluded_paths=excluded_paths, threshold=threshold)

    def set_active_scan_limits(self, *, max_duration: int=20, max_rule_duration: int=10, max_concurrency: int=5, request_delay_ms: int=0) -> None:
        """委托规范职责入口，保留调用契约。"""
        return set_active_scan_limits(self._state, max_duration=max_duration, max_rule_duration=max_rule_duration, max_concurrency=max_concurrency, request_delay_ms=request_delay_ms)

    def get_scan_progress(self, scan_ids: Iterable[str]=()) -> ZAPProgress:
        """委托规范职责入口，保留调用契约。"""
        return get_scan_progress(self._state, scan_ids)

    def stop_scan(self, scan_ids: Iterable[str]=()) -> None:
        """委托规范职责入口，保留调用契约。"""
        return stop_scan(self._state, scan_ids)

    def get_alerts(self, rule_ids: Iterable[str]=()) -> list[ZAPAlert]:
        """委托规范职责入口，保留调用契约。"""
        return get_alerts(self._state, rule_ids)

    def get_alert_counts(self, alerts: Iterable[ZAPAlert]) -> ZAPAlertCounts:
        """委托规范职责入口，保留调用契约。"""
        return get_alert_counts(self._state, alerts)

    def get_scan_statistics(self) -> tuple[ZAPPagesStats, ZAPAlertCounts]:
        """委托规范职责入口，保留调用契约。"""
        return get_scan_statistics(self._state, )

    def list_urls(self) -> list[str]:
        """委托规范职责入口，保留调用契约。"""
        return list_urls(self._state, )


    def close(self) -> None:
        """委托规范职责入口，保留调用契约。"""
        return close(self._state, )


__all__ = [
    'ZAP_REASON_UNAVAILABLE',
    'ZAP_REASON_API_AUTH_FAILED',
    'ZAP_REASON_PLUGIN_MISSING',
    'ZAP_REASON_VERSION_UNSUPPORTED',
    'ZAP_REASON_CONTEXT_FAILED',
    'ZAP_REASON_SPIDER_FAILED',
    'ZAP_REASON_ACTIVE_FAILED',
    'ZAP_REASON_BAD_RESPONSE',
    'ZAP_REASON_SCOPE_VIOLATION',
    'MIN_SUPPORTED_ZAP_VERSION',
    'MIN_SUPPORTED_VERSION_TEXT',
    'CAP_ABOUT',
    'CAP_SPIDER',
    'CAP_CLIENT_SPIDER',
    'CAP_AJAX_SPIDER',
    'CAP_PASSIVE',
    'CAP_ACTIVE',
    'CAP_OPENAPI',
    'CAP_AUTH',
    'CAP_SESSION',
    'CAP_SCANNER_POOL',
    'CAP_HISTORY',
    'CAP_URLS',
    'CAP_ACTIVE_LIMITS',
    'ACTIVE_MAX_DURATION_HARD_CAP',
    'ACTIVE_MAX_RULE_DURATION_HARD_CAP',
    'ACTIVE_MAX_CONCURRENCY_HARD_CAP',
    'ACTIVE_MIN_REQUEST_DELAY_MS',
    'ACTIVE_MAX_REQUEST_DELAY_MS',
    'ACTIVE_MAX_ALERTS_PER_RULE_HARD_CAP',
    'ACTIVE_DEPTH_HARD_CAP',
    'ZAPConnectorError',
    'parse_zap_version',
    'is_supported_version',
    'map_alert_severity',
]
