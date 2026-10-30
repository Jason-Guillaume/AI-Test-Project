"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from app.features.security_testing.zap.transport import ZAPTransportError
from app.features.security_testing.zap.protocol.common import ZAPConnectorError
from app.features.security_testing.zap.protocol.common import ZAPProtocolState
from app.features.security_testing.zap.protocol.common import ZAP_REASON_BAD_RESPONSE
from app.features.security_testing.zap.protocol.common import ZAP_REASON_UNAVAILABLE
from app.features.security_testing.zap.protocol.common import _describe
from app.features.security_testing.zap.protocol.common import _map_reason


def call(state: ZAPProtocolState, method: str, path: str, *, params: dict[str, Any] | None=None, json_body: dict[str, Any] | None=None, files: Any=None, timeout_seconds: float | None=None, _reason: str=ZAP_REASON_BAD_RESPONSE) -> Any:
    """发一次 ZAP 请求并把传输层错误映射成 Connector 错误。"""
    effective_timeout = timeout_seconds if timeout_seconds is not None else state.timeout
    try:
        return state.transport.request(
            method=method, path=path, params=params, json_body=json_body,
            files=files, timeout=effective_timeout,
        )
    except ZAPTransportError as exc:
        mapped = _map_reason(exc, default=_reason)
        # 只有「连不上 / 服务端 5xx」算可重试；鉴权失败与 4xx 重试没有意义。
        retryable = mapped == ZAP_REASON_UNAVAILABLE or (
            exc.status_code is not None and 500 <= exc.status_code < 600
        )
        raise ZAPConnectorError(
            _describe(exc.message, path=path),
            reason=mapped,
            status_code=exc.status_code,
            path=path,
            retryable=retryable,
        ) from exc
    except Exception as exc:  # noqa: BLE001 — 传输层实现可能抛其它异常
        # 兜底：任何非预期异常都收敛成不可重试的 Connector 错误，
        # 避免扫描器实现里的 bug 直接打挂 Worker 线程。
        raise ZAPConnectorError(
            f"ZAP 请求异常：{type(exc).__name__}", reason=ZAP_REASON_BAD_RESPONSE, path=path,
        ) from exc


def close(state: ZAPProtocolState) -> None:
    """关闭底层传输。幂等。"""
    state.transport.close()
