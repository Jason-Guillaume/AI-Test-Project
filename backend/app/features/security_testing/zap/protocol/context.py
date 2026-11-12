"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Iterable
from urllib.parse import urlsplit
from app.features.security_testing.zap.contracts import AUTH_MODE_NONE, ZAPScanContext
from app.features.security_testing.zap.protocol.common import ZAPConnectorError
from app.features.security_testing.zap.protocol.common import ZAPProtocolState
from app.features.security_testing.zap.protocol.common import ZAP_REASON_CONTEXT_FAILED
from app.features.security_testing.zap.protocol.common import ZAP_REASON_PLUGIN_MISSING
from app.features.security_testing.zap.protocol.common import ZAP_REASON_SCOPE_VIOLATION
from app.features.security_testing.zap.protocol.common import _to_regex
from app.features.security_testing.zap.protocol.transport import call


def assert_url_in_scope(state: ZAPProtocolState, url: str) -> None:
    """在下发任何扫描请求之前检查目标是否在已设置范围内。

    不能只靠 ZAP 的 in-scope 设置：它会在 spider 里返回负数扫描 ID，
    在 active scan 里则可能已经发出请求。范围校验必须在出站前完成（§十五）。
    未调用 apply_scope 时不做拦截——调用方负责先设置范围。
    """
    if not state.scope_hosts:
        return
    parts = urlsplit(str(url or ""))
    host = (parts.hostname or "").lower()
    if not host:
        raise ZAPConnectorError(
            f"扫描目标缺少主机名：{url}", reason=ZAP_REASON_SCOPE_VIOLATION,
        )
    if host not in state.scope_hosts:
        raise ZAPConnectorError(
            f"扫描目标 {host} 不在已设置的扫描范围内（允许：{', '.join(state.scope_hosts)}）",
            reason=ZAP_REASON_SCOPE_VIOLATION,
        )


def apply_scope(state: ZAPProtocolState, *, base_url: str, allowed_hosts: Iterable[str]=(), include_paths: Iterable[str]=(), exclude_paths: Iterable[str]=()) -> None:
    """把平台的范围配置写成 ZAP 的 scope 设置。

    顺序有讲究：先设 in-scope，再设 exclude-from-scan。
    exclude 是正则，路径需要转义；不做正则转义就是注入点。
    """
    parts = urlsplit(base_url)
    netloc = parts.netloc or urlsplit(str(base_url or "")).netloc
    if not netloc:
        raise ZAPConnectorError("扫描上下文缺少可解析的主机地址", reason=ZAP_REASON_CONTEXT_FAILED)
    hosts = [host.strip().lower() for host in allowed_hosts if host and host.strip()]
    if not hosts:
        hosts = [netloc.lower()]
    state.scope_hosts = hosts
    state.scope_base_url = base_url
    for host in hosts:
        call(state, "POST", "/JSON/core/setTargetInScope", json_body={"host": host},
                   timeout_seconds=10.0, _reason=ZAP_REASON_CONTEXT_FAILED)
    for path in include_paths:
        if path and path.strip():
            call(state, "POST", "/JSON/core/setTargetInScopeRegex",
                       json_body={"regex": _to_regex(base_url, path)},
                       timeout_seconds=10.0, _reason=ZAP_REASON_CONTEXT_FAILED)
    for path in exclude_paths:
        if path and path.strip():
            call(state, "POST", "/JSON/core/setTargetExcludeFromScanRegex",
                       json_body={"regex": _to_regex(base_url, path)},
                       timeout_seconds=10.0, _reason=ZAP_REASON_CONTEXT_FAILED)


def create_scan_context(state: ZAPProtocolState, *, host_pattern: str, context_name: str | None=None) -> ZAPScanContext:
    """创建扫描上下文句柄。

    第一版同一 ZAP 实例串行执行扫描，所以上下文是「当前配置」而不是持久资源；
    真正的隔离靠每次扫描前 apply_scope + clean_scan_context 清理。
    """
    pattern = (host_pattern or "").strip()
    if not pattern:
        raise ZAPConnectorError("扫描上下文缺少主机范围", reason=ZAP_REASON_CONTEXT_FAILED)
    try:
        if pattern.startswith(".") or pattern.endswith("*"):
            call(state, "POST", "/JSON/core/setTargetInScopePrefix", json_body={"host": pattern},
                       timeout_seconds=10.0, _reason=ZAP_REASON_CONTEXT_FAILED)
        else:
            call(state, "POST", "/JSON/core/setTargetInScope", json_body={"host": pattern},
                       timeout_seconds=10.0, _reason=ZAP_REASON_CONTEXT_FAILED)
        state.scan_ids = []
    except ZAPConnectorError:
        raise
    return ZAPScanContext(host_pattern=pattern, context_name=context_name)


def clean_scan_context(state: ZAPProtocolState) -> None:
    """清理 ZAP 侧的会话与认证状态。

    失败不抛错：清理失败会留下 ZAP 内部状态，但不该让扫描结果导入被拦下来。
    调用方（Worker）负责记录一条 WARNING 事件。
    """
    try:
        call(state, "POST", "/JSON/authentication/setAuthenticationMethod",
                   json_body={"value": "none"}, timeout_seconds=10.0)
        call(state, "POST", "/JSON/session/setSessionManagementMethod",
                   json_body={"value": "none"}, timeout_seconds=10.0)
        call(state, "POST", "/JSON/core/resetAll", timeout_seconds=20.0)
    except ZAPConnectorError as exc:
        if exc.reason == ZAP_REASON_PLUGIN_MISSING:
            # resetAll 在部分版本不存在；逐条清理即可。
            return
        raise
    finally:
        # 无论 ZAP 侧清理成功与否，都要清掉本地记录的认证能力位——
        # 否则上一个任务的浏览器登录态判定会串到下一个任务（§三十四 第 12 条）。
        state.scan_ids = []
        state.auth_mode = AUTH_MODE_NONE
        state.session_method = "none"
        state.has_session_value = False
