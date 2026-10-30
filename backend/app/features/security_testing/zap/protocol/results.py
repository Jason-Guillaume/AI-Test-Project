"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Iterable
from app.features.security_testing.zap.contracts import (
    ZAPAlert,
    ZAPAlertCounts,
    ZAPPagesStats,
    redact_text,
    redact_url,
)
from app.features.security_testing.zap.protocol.common import ZAPConnectorError
from app.features.security_testing.zap.protocol.common import ZAPProtocolState
from app.features.security_testing.zap.protocol.common import _int_of
from app.features.security_testing.zap.protocol.transport import call
from app.features.security_testing.zap.protocol.common import map_alert_severity


def get_alerts(state: ZAPProtocolState, rule_ids: Iterable[str]=()) -> list[ZAPAlert]:
    """拉取告警并转成平台结构。

    evidence / solution / attack 字段可能回显请求头里的凭据，
    在此处就地脱敏——不让原文进入事件表或 Finding（§二十一）。
    """
    body = call(state, "POST", "/JSON/core/alertJson", timeout_seconds=30.0)
    items = body if isinstance(body, list) else []
    wanted = {str(r).strip() for r in rule_ids if r and str(r).strip()}
    alerts: list[ZAPAlert] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("id") or item.get("ruleId") or "")
        if wanted and rule_id not in wanted:
            continue
        confidence = _int_of(item.get("confidence"))
        if confidence is None or not (1 <= confidence <= 5):
            confidence = 5
        name = str(item.get("alert") or item.get("name") or "").strip()
        if not rule_id and not name:
            continue
        cwe = _int_of(item.get("cweId"))
        wasc = _int_of(item.get("wascId"))
        alerts.append(
            ZAPAlert(
                rule_id=rule_id,
                name=name or f"未命名规则 {rule_id}",
                risk=str(item.get("risk") or "").strip(),
                confidence=confidence,
                url=redact_url(str(item.get("url") or "")),
                method=str(item.get("method") or "").upper(),
                parameter=str(item.get("param") or ""),
                description=redact_text(str(item.get("description") or item.get("name") or "")),
                remediation=redact_text(str(item.get("solution") or item.get("remediation") or "")),
                evidence=redact_text(str(item.get("evidence") or "")),
                cwe_id=cwe if cwe and cwe > 0 else None,
                wasc_id=wasc if wasc and wasc > 0 else None,
                reference=str(item.get("reference") or ""),
            )
        )
    return alerts


def get_alert_counts(state: ZAPProtocolState, alerts: Iterable[ZAPAlert]) -> ZAPAlertCounts:
    """按平台 Severity 汇总告警数（Severity 映射见 contracts.map_zap_risk）。"""
    counts = ZAPAlertCounts()
    for alert in alerts:
        severity = map_alert_severity(alert.risk)
        counts.total += 1
        if severity == "HIGH":
            counts.high += 1
        elif severity == "MEDIUM":
            counts.medium += 1
        elif severity == "LOW":
            counts.low += 1
        else:
            counts.info += 1
    return counts


def get_scan_statistics(state: ZAPProtocolState) -> tuple[ZAPPagesStats, ZAPAlertCounts]:
    """返回爬取统计与告警汇总。

    ZAP 在不同版本上 countAlerts / urls / history 可用性不一，
    任何一个失败都降级为 0 而不是抛错——统计缺失不能阻断结果导入。
    """
    pages = 0
    urls = 0
    requests = 0
    try:
        body = call(state, "GET", "/JSON/core/urls", timeout_seconds=15.0)
        urls = len(body) if isinstance(body, list) else 0
    except ZAPConnectorError:
        pass
    try:
        body = call(state, "POST", "/JSON/pscan/progress", timeout_seconds=15.0)
        if isinstance(body, dict):
            pages = _int_of(body.get("ScannedCount")) or pages
            requests = _int_of(body.get("QueuedUrls")) or requests
    except ZAPConnectorError:
        pass
    alerts = get_alerts(state, )
    stats = ZAPPagesStats(pages=pages or urls, requests=requests, urls=urls)
    return stats, get_alert_counts(state, alerts)


def list_urls(state: ZAPProtocolState) -> list[str]:
    """列出已发现的 URL（用于覆盖率统计）。端点不可用时返回空列表。

    URL 的凭据参数值在返回前抹掉——覆盖率行会入库。
    """
    try:
        body = call(state, "GET", "/JSON/core/urls", timeout_seconds=15.0)
    except ZAPConnectorError:
        return []
    if not isinstance(body, list):
        return []
    return [redact_url(str(u)) for u in body]
