"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from typing import Any
from app.features.security_testing.zap.contracts import ZAPAbout, ZAPCapability, ZAPCapabilities
from app.features.security_testing.zap.protocol.common import CAP_ABOUT
from app.features.security_testing.zap.protocol.common import CAP_ACTIVE
from app.features.security_testing.zap.protocol.common import CAP_ACTIVE_LIMITS
from app.features.security_testing.zap.protocol.common import CAP_CLIENT_SPIDER
from app.features.security_testing.zap.protocol.common import CAP_HISTORY
from app.features.security_testing.zap.protocol.common import CAP_PASSIVE
from app.features.security_testing.zap.protocol.common import CAP_SCANNER_POOL
from app.features.security_testing.zap.protocol.common import CAP_SESSION
from app.features.security_testing.zap.protocol.common import CAP_SPIDER
from app.features.security_testing.zap.protocol.common import CAP_URLS
from app.features.security_testing.zap.protocol.common import MIN_SUPPORTED_VERSION_TEXT
from app.features.security_testing.zap.protocol.common import ZAPConnectorError
from app.features.security_testing.zap.protocol.common import ZAPProtocolState
from app.features.security_testing.zap.protocol.common import ZAP_REASON_BAD_RESPONSE
from app.features.security_testing.zap.protocol.common import ZAP_REASON_PLUGIN_MISSING
from app.features.security_testing.zap.protocol.common import ZAP_REASON_VERSION_UNSUPPORTED
from app.features.security_testing.zap.protocol.common import _ADDON_TO_CAPABILITY
from app.features.security_testing.zap.protocol.transport import call
from app.features.security_testing.zap.protocol.common import is_supported_version


def check_health(state: ZAPProtocolState) -> ZAPAbout:
    """健康检查 + 版本与插件清单。

    Raises:
        ZAPConnectorError: 连不上、API Key 无效、版本不受支持。
    """
    about = read_about(state, )
    if not is_supported_version(about.version):
        raise ZAPConnectorError(
            f"ZAP 版本不受支持：{about.version or '未知'}（最低要求 {MIN_SUPPORTED_VERSION_TEXT}）",
            reason=ZAP_REASON_VERSION_UNSUPPORTED,
            status_code=426,
        )
    return about


def get_version(state: ZAPProtocolState) -> str:
    """只取版本号；连不上抛错，但不做版本下限判断（用于能力页展示真实版本）。"""
    return read_about(state, ).version


def get_capabilities(state: ZAPProtocolState) -> ZAPCapabilities:
    """探测版本 + 插件能力。

    探测只用**只读**端点（isRunning / get* / verify / list），绝不发会改变 ZAP 状态的
    调用——否则「查一下能力」本身就会启动一次爬取。add-on 清单能判定的不重复探测。
    """
    try:
        about = read_about(state, )
    except ZAPConnectorError as exc:
        # 连不上时能力页仍然要能显示「服务不可用」，而不是整页报错。
        about = ZAPAbout(version="unknown", add_on_names=[])
        return ZAPCapabilities(
            version="unknown",
            about=about,
            capabilities=[ZAPCapability(name=CAP_ABOUT, supported=False, detail=exc.message)],
        )

    capabilities: list[ZAPCapability] = [
        ZAPCapability(
            name=CAP_ABOUT,
            supported=is_supported_version(about.version),
            detail=f"version={about.version or '未知'}"
            + ("" if is_supported_version(about.version) else f"，低于最低要求 {MIN_SUPPORTED_VERSION_TEXT}"),
        ),
    ]

    # 1) add-on 清单能直接判定的组件（一次 about 调用，不额外发请求）。
    for name in about.add_on_names:
        capability = _ADDON_TO_CAPABILITY.get(name.lower())
        if capability and not has_capability(state, capabilities, capability):
            capabilities.append(
                ZAPCapability(
                    name=capability,
                    supported=True,
                    detail=f"add-on {name}（版本 {about.add_on_versions.get(name, '')}）",
                )
            )

    # 2) core 内置组件：有 about 响应就说明这些在跑。
    for name in (CAP_SPIDER, CAP_PASSIVE, CAP_ACTIVE, CAP_SESSION):
        capabilities.append(ZAPCapability(name=name, supported=True, detail="core 内置"))

    # 3) 端点存在性探测（全部只读）。
    probe_capability(state, capabilities, CAP_CLIENT_SPIDER, method="POST",
                           path="/JSON/clientspider/isClientSpiderRunning")
    probe_capability(state, capabilities, CAP_HISTORY, method="GET", path="/JSON/core/history",
                           probe_params={"start": 0, "count": 1})
    probe_capability(state, capabilities, CAP_URLS, method="GET", path="/JSON/core/urls")
    probe_capability(state, capabilities, CAP_SCANNER_POOL, method="GET", path="/JSON/scannerpool/list")

    # 4) 主动扫描限额能力：只读 getAttackPolicy 能证明 ascan 生效。
    probe_capability(state, capabilities, CAP_ACTIVE_LIMITS, method="POST",
                           path="/JSON/ascan/getAttackPolicy")

    return ZAPCapabilities(version=about.version, about=about, capabilities=capabilities)


def has_capability(state: ZAPProtocolState, capabilities: list[ZAPCapability], name: str) -> bool:
    """判断是否包含`capability`是否成立。"""
    return any(cap.name == name for cap in capabilities)


def probe_capability(state: ZAPProtocolState, capabilities: list[ZAPCapability], name: str, *, method: str, path: str, probe_params: dict[str, Any] | None=None) -> None:
    """探测一个端点是否存在。任何异常都只降级成 supported=False。"""
    if has_capability(state, capabilities, name):
        return
    try:
        call(state, method, path, params=probe_params, timeout_seconds=10.0,
                   _reason=ZAP_REASON_PLUGIN_MISSING)
        capabilities.append(ZAPCapability(name=name, supported=True, detail="端点探测通过"))
    except ZAPConnectorError as exc:
        detail = "组件端点不存在" if exc.reason == ZAP_REASON_PLUGIN_MISSING else exc.message
        capabilities.append(ZAPCapability(name=name, supported=False, detail=detail))


def read_about(state: ZAPProtocolState) -> ZAPAbout:
    """调 /JSON/core/about 并转成平台结构。"""
    try:
        body = call(state, "GET", "/JSON/core/about", params={"format": "json"})
    except ZAPConnectorError:
        raise
    if not isinstance(body, dict):
        raise ZAPConnectorError("ZAP 返回了非预期的 about 响应", reason=ZAP_REASON_BAD_RESPONSE)
    version = str(body.get("version") or "")
    add_ons = body.get("addOns") or []
    names: list[str] = []
    versions: dict[str, str] = {}
    for item in add_ons:
        if isinstance(item, dict):
            name = str(item.get("name") or "")
            if name:
                names.append(name)
                versions[name] = str(item.get("version") or "")
        elif isinstance(item, str):
            names.append(item)
    return ZAPAbout(version=version, add_on_names=names, add_on_versions=versions)
