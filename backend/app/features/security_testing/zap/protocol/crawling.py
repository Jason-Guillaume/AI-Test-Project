"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any, Iterable
from app.features.security_testing.zap.protocol.common import ACTIVE_DEPTH_HARD_CAP
from app.features.security_testing.zap.protocol.common import ZAPConnectorError
from app.features.security_testing.zap.protocol.common import ZAPProtocolState
from app.features.security_testing.zap.protocol.common import ZAP_REASON_PLUGIN_MISSING
from app.features.security_testing.zap.protocol.common import ZAP_REASON_SPIDER_FAILED
from app.features.security_testing.zap.protocol.common import ZAP_REASON_UNAVAILABLE
from app.features.security_testing.zap.protocol.common import _escape_regex
from app.features.security_testing.zap.protocol.common import _string_of
from app.features.security_testing.zap.protocol.context import assert_url_in_scope
from app.features.security_testing.zap.protocol.transport import call


def start_spider(state: ZAPProtocolState, url: str, *, max_depth: int=3, max_children: int=10, max_threads: int=10, exclude_patterns: Iterable[str]=()) -> dict[str, Any]:
    """启动传统 Spider。

    max_depth 截断到硬上限：传统 Spider 深度无上限会把整站拉进来。
    """
    assert_url_in_scope(state, url)
    depth = max(1, min(int(max_depth or 3), ACTIVE_DEPTH_HARD_CAP))
    children = max(1, min(int(max_children or 10), 100))
    threads = max(1, min(int(max_threads or 10), 30))
    body: dict[str, Any] = {
        "url": url,
        "maxDepth": depth,
        "maxChildren": children,
        "threads": threads,
    }
    patterns = [p for p in exclude_patterns if p and p.strip()]
    if patterns:
        body["excludePathsRegex"] = "|".join(_escape_regex(p) for p in patterns[:50])
    try:
        result = call(state, "POST", "/JSON/spider/spider", json_body=body, timeout_seconds=30.0)
    except ZAPConnectorError as exc:
        if exc.reason in (ZAP_REASON_PLUGIN_MISSING, ZAP_REASON_UNAVAILABLE):
            raise ZAPConnectorError("启动 Spider 失败", reason=ZAP_REASON_SPIDER_FAILED) from exc
        raise
    scan_ref = _string_of(result, "scan", result) if isinstance(result, dict) else str(result)
    if scan_ref and str(scan_ref).lstrip("-").isdigit() and int(str(scan_ref)) < 0:
        raise ZAPConnectorError("Spider 拒绝启动（目标不在扫描范围内）", reason=ZAP_REASON_SPIDER_FAILED)
    return {"scan_ref": str(scan_ref)}


def start_client_spider(state: ZAPProtocolState, url: str, *, max_depth: int=5, page_count: int=0, target_regex: str='', user_agent_script: str='') -> dict[str, Any]:
    """启动 Client Spider（真实浏览器渲染）。

    page_count=0 表示不限页面数——但受 max_depth 约束。
    user_agent_script 用于把 XSRF token 等写进前端请求。
    """
    assert_url_in_scope(state, url)
    depth = max(1, min(int(max_depth or 5), ACTIVE_DEPTH_HARD_CAP))
    try:
        call(state, "POST", "/JSON/clientspider/setMaxCrawlDepth",
                   json_body={"maxCrawlDepth": depth}, timeout_seconds=10.0,
                   _reason=ZAP_REASON_PLUGIN_MISSING)
        if int(page_count or 0) > 0:
            call(state, "POST", "/JSON/clientspider/setPageCount",
                       json_body={"pageCount": int(page_count)}, timeout_seconds=10.0,
                       _reason=ZAP_REASON_PLUGIN_MISSING)
        regex = (target_regex or "").strip()
        if regex:
            call(state, "POST", "/JSON/clientspider/setTargetRegex",
                       json_body={"targetRegex": regex}, timeout_seconds=10.0,
                       _reason=ZAP_REASON_PLUGIN_MISSING)
        script = (user_agent_script or "").strip()
        if script:
            call(state, "POST", "/JSON/authentication/setUserAgent", json_body={"script": script},
                       timeout_seconds=10.0)
        result = call(state, "POST", "/JSON/clientspider/clientspider", json_body={"url": url},
                            timeout_seconds=30.0, _reason=ZAP_REASON_PLUGIN_MISSING)
    except ZAPConnectorError as exc:
        if exc.reason == ZAP_REASON_PLUGIN_MISSING:
            raise ZAPConnectorError(
                "ZAP 不支持 Client Spider，无法爬取前端路由页面",
                reason=ZAP_REASON_PLUGIN_MISSING,
            ) from exc
        raise
    return {"scan_ref": _string_of(result, "id", "") if isinstance(result, dict) else ""}
