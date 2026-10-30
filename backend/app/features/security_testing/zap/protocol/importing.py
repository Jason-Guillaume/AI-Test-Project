"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from app.features.security_testing.zap.protocol.common import ZAPConnectorError
from app.features.security_testing.zap.protocol.common import ZAPProtocolState
from app.features.security_testing.zap.protocol.common import ZAP_REASON_CONTEXT_FAILED
from app.features.security_testing.zap.protocol.common import ZAP_REASON_PLUGIN_MISSING
from app.features.security_testing.zap.protocol.transport import call


def import_openapi(state: ZAPProtocolState, document: str, *, file_name: str='openapi.json') -> dict[str, Any]:
    """导入 OpenAPI 3 文档。

    document 是**平台重建的** OpenAPI（见 openapi_export.py），不是用户原文——
    原文档中的 servers 字段可能指向未授权域名，导入前已在导出层剥离。
    """
    text = (document or "").strip()
    if not text:
        raise ZAPConnectorError("OpenAPI 文档为空", reason=ZAP_REASON_CONTEXT_FAILED)
    try:
        body = call(state,
            "POST", "/JSON/openapi/add",
            files={"api_file": (file_name, text.encode("utf-8"), "application/json")},
            timeout_seconds=60.0,
            _reason=ZAP_REASON_CONTEXT_FAILED,
        )
    except ZAPConnectorError as exc:
        if exc.reason == ZAP_REASON_PLUGIN_MISSING:
            raise ZAPConnectorError(
                "ZAP 缺少 OpenAPI 支持组件，无法导入 API 定义",
                reason=ZAP_REASON_PLUGIN_MISSING,
            ) from exc
        raise
    return body if isinstance(body, dict) else {"raw": body}
