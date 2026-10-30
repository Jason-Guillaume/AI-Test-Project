"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from app.features.security_testing.zap.schemas import ZapHealthRead


def get_zap_state_snapshot():
    """读 ZAP 配置状态（延迟导入，避免测试里提前绑定 settings）。"""
    from app.features.security_testing.zap.client import get_zap_state

    return get_zap_state()


def health() -> ZapHealthRead:
    """ZAP 服务健康（不含任何密钥，也不发起网络请求）。"""
    state = get_zap_state_snapshot()
    available = bool(state.enabled and state.configured)
    return ZapHealthRead(
        enabled=bool(state.enabled),
        available=available,
        version=None,
        reachable=available,
        api_key_configured=bool(state.api_key_configured),
        message=state.message or ("ZAP 服务已配置" if available else "ZAP 服务未启用或未配置"),
    )


def empty_capabilities(message: str) -> dict[str, Any]:
    """能力探测失败时的空结果：available=False，不让前端误判为已支持。"""
    return {
        "version": None,
        "available": False,
        "message": message,
        "addon_names": [],
        "addon_versions": {},
        "capabilities": [],
    }


def capabilities() -> dict[str, Any]:
    """ZAP 能力清单（只读探测；服务不可达时返回 available=False 而不是抛错）。

    探测只走 about / isRunning / get* 这类**只读**接口，绝不触发扫描动作。
    """
    from app.features.security_testing.zap.client import build_connector, get_zap_state

    state = get_zap_state()
    if not (state.enabled and state.configured):
        return empty_capabilities(state.message or "ZAP 服务未启用或未配置")

    connector = None
    try:
        connector = build_connector()
        caps = connector.get_capabilities()
        return {
            "version": caps.version,
            "available": True,
            "message": "ZAP 服务可访问",
            "addon_names": list(caps.about.add_on_names),
            "addon_versions": dict(caps.about.add_on_versions),
            "capabilities": [cap.as_dict() for cap in caps.capabilities],
        }
    except Exception as exc:  # noqa: BLE001 - 能力页不能因为 ZAP 不可用而整页报错
        return empty_capabilities(f"ZAP 服务不可访问：{exc}")
    finally:
        if connector is not None:
            try:
                connector.close()
            except Exception:  # noqa: BLE001
                pass
