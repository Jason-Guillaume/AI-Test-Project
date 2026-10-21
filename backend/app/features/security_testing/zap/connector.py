"""ZAP Connector：平台与 ZAP 之间唯一的翻译层。

为什么单独一层（而不是 Router / Service 直接拼 ZAP 请求）：
1. **范围限制在这里落地**。所有发往 ZAP 的 URL 都先过 scope 守卫，
   不只在创建任务时校验一次（§十五「必须在所有扫描请求发出前实施范围限制」）。
2. **凭据只在这里出现一次**。Token 由调用方以参数传入，传给 ZAP 的 session 配置后立即丢弃；
   Connector 不缓存、不打印、不落库（§十一、§三十四 第 8 条）。
3. **ZAP 的字段名不会外泄**。上层只拿到 ZAPAlert / ZAPProgress 等平台数据类。

不做的事：
- 不重试。ZAP 扫描动作是有副作用的，静默重放会重复发攻击请求；
  重试交给 Worker，且必须显式记录。
- 不做数据库操作。Connector 是纯 API 客户端，Worker 负责落库与状态机。
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from app.features.security_testing.zap.contracts import (
    AUTH_STATUS_LOGGED_IN,
    AUTH_STATUS_LOGGED_OUT,
    AUTH_STATUS_UNVERIFIABLE,
    AUTH_MODE_MANUAL,
    AUTH_MODE_NONE,
    REDACTED_PLACEHOLDER,
    ZAPAbout,
    ZAPAlert,
    ZAPAlertCounts,
    ZAPAuthResult,
    ZAPCapability,
    ZAPCapabilities,
    ZAPPagesStats,
    ZAPProgress,
    ZAPScanContext,
    redact_text,
    redact_url,
)
from app.features.security_testing.zap.transport import ZAPTransport, ZAPTransportError

#: Connector 层错误原因。上层按 reason 映射成 SECURITY_SCAN_* 业务错误码，
#: Connector 本身不认识业务错误码，也不认识数据库。
ZAP_REASON_UNAVAILABLE = "ZAP_SERVICE_UNAVAILABLE"
ZAP_REASON_API_AUTH_FAILED = "ZAP_API_AUTH_FAILED"
ZAP_REASON_PLUGIN_MISSING = "ZAP_PLUGIN_MISSING"
ZAP_REASON_VERSION_UNSUPPORTED = "ZAP_VERSION_UNSUPPORTED"
ZAP_REASON_CONTEXT_FAILED = "ZAP_CONTEXT_FAILED"
ZAP_REASON_SPIDER_FAILED = "ZAP_SPIDER_FAILED"
ZAP_REASON_ACTIVE_FAILED = "ZAP_ACTIVE_FAILED"
ZAP_REASON_BAD_RESPONSE = "ZAP_BAD_RESPONSE"
ZAP_REASON_SCOPE_VIOLATION = "SECURITY_SCAN_SCOPE_VIOLATION"

#: 最低的 ZAP 版本。Client Spider / OpenAPI Support / Authentication Helper
#: 在这个版本上行为才稳定；低于它按不受支持处理而不是继续跑。
MIN_SUPPORTED_ZAP_VERSION = (2, 12, 0)
MIN_SUPPORTED_VERSION_TEXT = "2.12.0"

#: 能力名。前端按名称显示「受限」而不是假装成功（§三 第 7 条、§十二）。
CAP_ABOUT = "core.about"
CAP_SPIDER = "spider"
CAP_CLIENT_SPIDER = "clientspider"
CAP_AJAX_SPIDER = "ajaxspider"
CAP_PASSIVE = "passive"
CAP_ACTIVE = "active"
CAP_OPENAPI = "openapi"
CAP_AUTH = "authentication"
CAP_SESSION = "session"
CAP_SCANNER_POOL = "scannerpool"
CAP_HISTORY = "core.history"
CAP_URLS = "core.urls"
CAP_ACTIVE_LIMITS = "active.limits"

#: 组件名 → 能力名的对应关系。add-on 名带大小写，做归一化匹配。
_ADDON_TO_CAPABILITY: dict[str, str] = {
    "clientSpider": CAP_CLIENT_SPIDER,
    "ajaxSpider": CAP_AJAX_SPIDER,
    "openapi": CAP_OPENAPI,
    "authhelper": CAP_AUTH,
    "openapiSupport": CAP_OPENAPI,
}

#: 主动扫描硬上限。即使 Profile 传更大的值也截断到这里，
#: 避免一个配置错误把被测系统打挂（§十五）。
ACTIVE_MAX_DURATION_HARD_CAP = 60          # 分钟
ACTIVE_MAX_RULE_DURATION_HARD_CAP = 20     # 分钟
ACTIVE_MAX_CONCURRENCY_HARD_CAP = 20       # 线程
ACTIVE_MIN_REQUEST_DELAY_MS = 0
ACTIVE_MAX_REQUEST_DELAY_MS = 2000         # 毫秒
ACTIVE_MAX_ALERTS_PER_RULE_HARD_CAP = 50
ACTIVE_DEPTH_HARD_CAP = 8


class ZAPConnectorError(Exception):
    """Connector 层错误。

    reason 是稳定的标识符（可直接映射业务错误码）；
    message 是给人看的中文说明，不含 API Key / Token / 响应体原文。
    """

    def __init__(
        self,
        message: str,
        *,
        reason: str,
        status_code: int | None = None,
        path: str = "",
        retryable: bool = False,
    ) -> None:
        """初始化错误。"""
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.status_code = status_code
        self.path = path
        # retryable=True 仅表示「重连后可能成功」，是否重试由 Worker 决定并记录。
        self.retryable = retryable


def parse_zap_version(version: str) -> tuple[int, ...] | None:
    """解析 "2.16.0" → (2, 16, 0)；无法解析返回 None。"""
    parts = (version or "").strip().split(".")
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    if not numbers:
        return None
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers[:3])  # type: ignore[return-value]


def is_supported_version(version: str) -> bool:
    """是否 >= 最低支持版本。"""
    parsed = parse_zap_version(version)
    if parsed is None:
        return False
    return parsed >= MIN_SUPPORTED_ZAP_VERSION


class ZAPConnector:
    """ZAP 连接器。一个实例对应一个 ZAP 实例（同一个全局配置域）。

    线程安全约定：本类不做状态共享缓存，除 transport 外无可变状态，
    可以安全地被多个 Worker 线程复用（Worker 自己保证同一 ZAP 实例串行扫描）。
    """

    def __init__(self, transport: ZAPTransport, *, timeout_seconds: float = 30.0) -> None:
        """初始化。transport 由调用方构造（测试用 Mock，生产用 HttpZAPTransport）。"""
        self._transport = transport
        self._timeout = float(timeout_seconds)
        # 当前上下文的扫描引用（ZAP 侧），用于 stop/clean。
        self._scan_ids: list[str] = []
        # 当前配置的认证方式（只记能力位，不保留凭据值本身）。
        self._auth_mode: str = AUTH_MODE_NONE
        self._session_method: str = "none"
        self._has_session_value: bool = False
        # apply_scope 之后的允许主机集合（小写）；空表示尚未设置范围。
        self._scope_hosts: list[str] = []
        self._scope_base_url: str = ""

    def _assert_url_in_scope(self, url: str) -> None:
        """在下发任何扫描请求之前检查目标是否在已设置范围内。

        不能只靠 ZAP 的 in-scope 设置：它会在 spider 里返回负数扫描 ID，
        在 active scan 里则可能已经发出请求。范围校验必须在出站前完成（§十五）。
        未调用 apply_scope 时不做拦截——调用方负责先设置范围。
        """
        if not self._scope_hosts:
            return
        parts = urlsplit(str(url or ""))
        host = (parts.hostname or "").lower()
        if not host:
            raise ZAPConnectorError(
                f"扫描目标缺少主机名：{url}", reason=ZAP_REASON_SCOPE_VIOLATION,
            )
        if host not in self._scope_hosts:
            raise ZAPConnectorError(
                f"扫描目标 {host} 不在已设置的扫描范围内（允许：{', '.join(self._scope_hosts)}）",
                reason=ZAP_REASON_SCOPE_VIOLATION,
            )

    # ------------------------------------------------------------------ 基础信息

    def check_health(self) -> ZAPAbout:
        """健康检查 + 版本与插件清单。

        Raises:
            ZAPConnectorError: 连不上、API Key 无效、版本不受支持。
        """
        about = self._about()
        if not is_supported_version(about.version):
            raise ZAPConnectorError(
                f"ZAP 版本不受支持：{about.version or '未知'}（最低要求 {MIN_SUPPORTED_VERSION_TEXT}）",
                reason=ZAP_REASON_VERSION_UNSUPPORTED,
                status_code=426,
            )
        return about

    def get_version(self) -> str:
        """只取版本号；连不上抛错，但不做版本下限判断（用于能力页展示真实版本）。"""
        return self._about().version

    def get_capabilities(self) -> ZAPCapabilities:
        """探测版本 + 插件能力。

        探测只用**只读**端点（isRunning / get* / verify / list），绝不发会改变 ZAP 状态的
        调用——否则「查一下能力」本身就会启动一次爬取。add-on 清单能判定的不重复探测。
        """
        try:
            about = self._about()
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
            if capability and not self._has_capability(capabilities, capability):
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
        self._probe_capability(capabilities, CAP_CLIENT_SPIDER, method="POST",
                               path="/JSON/clientspider/isClientSpiderRunning")
        self._probe_capability(capabilities, CAP_HISTORY, method="GET", path="/JSON/core/history",
                               probe_params={"start": 0, "count": 1})
        self._probe_capability(capabilities, CAP_URLS, method="GET", path="/JSON/core/urls")
        self._probe_capability(capabilities, CAP_SCANNER_POOL, method="GET", path="/JSON/scannerpool/list")

        # 4) 主动扫描限额能力：只读 getAttackPolicy 能证明 ascan 生效。
        self._probe_capability(capabilities, CAP_ACTIVE_LIMITS, method="POST",
                               path="/JSON/ascan/getAttackPolicy")

        return ZAPCapabilities(version=about.version, about=about, capabilities=capabilities)

    def _has_capability(self, capabilities: list[ZAPCapability], name: str) -> bool:
        return any(cap.name == name for cap in capabilities)

    def _probe_capability(
        self,
        capabilities: list[ZAPCapability],
        name: str,
        *,
        method: str,
        path: str,
        probe_params: dict[str, Any] | None = None,
    ) -> None:
        """探测一个端点是否存在。任何异常都只降级成 supported=False。"""
        if self._has_capability(capabilities, name):
            return
        try:
            self._call(method, path, params=probe_params, timeout_seconds=10.0,
                       _reason=ZAP_REASON_PLUGIN_MISSING)
            capabilities.append(ZAPCapability(name=name, supported=True, detail="端点探测通过"))
        except ZAPConnectorError as exc:
            detail = "组件端点不存在" if exc.reason == ZAP_REASON_PLUGIN_MISSING else exc.message
            capabilities.append(ZAPCapability(name=name, supported=False, detail=detail))

    def _about(self) -> ZAPAbout:
        """调 /JSON/core/about 并转成平台结构。"""
        try:
            body = self._call("GET", "/JSON/core/about", params={"format": "json"})
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

    # ------------------------------------------------------------------ 扫描上下文

    def apply_scope(
        self,
        *,
        base_url: str,
        allowed_hosts: Iterable[str] = (),
        include_paths: Iterable[str] = (),
        exclude_paths: Iterable[str] = (),
    ) -> None:
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
        self._scope_hosts = hosts
        self._scope_base_url = base_url
        for host in hosts:
            self._call("POST", "/JSON/core/setTargetInScope", json_body={"host": host},
                       timeout_seconds=10.0, _reason=ZAP_REASON_CONTEXT_FAILED)
        for path in include_paths:
            if path and path.strip():
                self._call("POST", "/JSON/core/setTargetInScopeRegex",
                           json_body={"regex": _to_regex(base_url, path)},
                           timeout_seconds=10.0, _reason=ZAP_REASON_CONTEXT_FAILED)
        for path in exclude_paths:
            if path and path.strip():
                self._call("POST", "/JSON/core/setTargetExcludeFromScanRegex",
                           json_body={"regex": _to_regex(base_url, path)},
                           timeout_seconds=10.0, _reason=ZAP_REASON_CONTEXT_FAILED)

    def create_scan_context(self, *, host_pattern: str, context_name: str | None = None) -> ZAPScanContext:
        """创建扫描上下文句柄。

        第一版同一 ZAP 实例串行执行扫描，所以上下文是「当前配置」而不是持久资源；
        真正的隔离靠每次扫描前 apply_scope + clean_scan_context 清理。
        """
        pattern = (host_pattern or "").strip()
        if not pattern:
            raise ZAPConnectorError("扫描上下文缺少主机范围", reason=ZAP_REASON_CONTEXT_FAILED)
        try:
            if pattern.startswith(".") or pattern.endswith("*"):
                self._call("POST", "/JSON/core/setTargetInScopePrefix", json_body={"host": pattern},
                           timeout_seconds=10.0, _reason=ZAP_REASON_CONTEXT_FAILED)
            else:
                self._call("POST", "/JSON/core/setTargetInScope", json_body={"host": pattern},
                           timeout_seconds=10.0, _reason=ZAP_REASON_CONTEXT_FAILED)
            self._scan_ids = []
        except ZAPConnectorError:
            raise
        return ZAPScanContext(host_pattern=pattern, context_name=context_name)

    def clean_scan_context(self) -> None:
        """清理 ZAP 侧的会话与认证状态。

        失败不抛错：清理失败会留下 ZAP 内部状态，但不该让扫描结果导入被拦下来。
        调用方（Worker）负责记录一条 WARNING 事件。
        """
        try:
            self._call("POST", "/JSON/authentication/setAuthenticationMethod",
                       json_body={"value": "none"}, timeout_seconds=10.0)
            self._call("POST", "/JSON/session/setSessionManagementMethod",
                       json_body={"value": "none"}, timeout_seconds=10.0)
            self._call("POST", "/JSON/core/resetAll", timeout_seconds=20.0)
        except ZAPConnectorError as exc:
            if exc.reason == ZAP_REASON_PLUGIN_MISSING:
                # resetAll 在部分版本不存在；逐条清理即可。
                return
            raise
        finally:
            # 无论 ZAP 侧清理成功与否，都要清掉本地记录的认证能力位——
            # 否则上一个任务的浏览器登录态判定会串到下一个任务（§三十四 第 12 条）。
            self._scan_ids = []
            self._auth_mode = AUTH_MODE_NONE
            self._session_method = "none"
            self._has_session_value = False

    # ------------------------------------------------------------------ 认证

    def configure_authentication(self, auth: Mapping[str, Any]) -> ZAPAuthResult:
        """配置认证并把登录态验证结果返回。

        auth 支持的键（其余忽略）：
            auth_mode: NONE / BEARER_TOKEN / HEADER_BASED / BROWSER_AUTH / MANUAL
            session_method: none / headerBased / cookieBased
            session_header: 如 "Authorization"
            session_name:   如 "X-Auth-Token"
            session_value:  **明文凭据，传完即用，本方法不做任何留存**
            logged_in_indicator / logged_out_indicator: 登录态判定正则
            user_agent_script: JS 片段（设置 XSRF token 等）
            strategy: manual / usernamePassword
        """
        mode = str(auth.get("auth_mode") or AUTH_MODE_NONE)
        session_method = str(auth.get("session_method") or "none")
        self._auth_mode = mode
        self._session_method = session_method
        self._has_session_value = bool(str(auth.get("session_value") or "").strip())
        try:
            self._call("POST", "/JSON/authentication/setAuthenticationMethod",
                       json_body={"value": mode}, timeout_seconds=10.0)
            self._call("POST", "/JSON/session/setSessionManagementMethod",
                       json_body={"value": session_method}, timeout_seconds=10.0)
            if session_method not in ("none", ""):
                header = str(auth.get("session_header") or "")
                name = str(auth.get("session_name") or "")
                if header:
                    self._call("POST", "/JSON/session/setHeader", json_body={"header": header},
                               timeout_seconds=10.0)
                if name:
                    self._call("POST", "/JSON/session/setName", json_body={"value": name},
                               timeout_seconds=10.0)
                self._call("POST", "/JSON/session/setValue",
                           json_body={"value": str(auth.get("session_value") or "")},
                           timeout_seconds=10.0)
                # headerBased 模式必须告诉 ZAP 这是 header，不是 cookie。
                self._call("POST", "/JSON/session/setTokenName",
                           json_body={"value": header or name}, timeout_seconds=10.0)
            indicator = str(auth.get("logged_in_indicator") or "")
            out_indicator = str(auth.get("logged_out_indicator") or "")
            if indicator:
                self._call("POST", "/JSON/authentication/setLoggedInIndicator",
                           json_body={"regex": indicator}, timeout_seconds=10.0)
            if out_indicator:
                self._call("POST", "/JSON/authentication/setLoggedOutIndicator",
                           json_body={"regex": out_indicator}, timeout_seconds=10.0)
            script = str(auth.get("user_agent_script") or "")
            if script:
                self._call("POST", "/JSON/authentication/setUserAgent", json_body={"script": script},
                           timeout_seconds=10.0)
            strategy = str(auth.get("strategy") or "manual")
            self._call("POST", "/JSON/authentication/setAuthenticationStrategy",
                       json_body={"value": strategy}, timeout_seconds=10.0)
        except ZAPConnectorError:
            raise

        authenticated, verified = self.verify_authentication()
        if authenticated:
            status = AUTH_STATUS_LOGGED_IN
        elif verified:
            status = AUTH_STATUS_LOGGED_OUT
        else:
            status = AUTH_STATUS_UNVERIFIABLE
        return ZAPAuthResult(
            authenticated=authenticated,
            verified=verified,
            auth_mode=mode,
            status=status,
            detail=(_auth_detail(session_method, authenticated, verified)),
        )

    def verify_authentication(self) -> tuple[bool, bool]:
        """调用 ZAP 验证当前认证是否有效，返回 (authenticated, verified)。

        ZAP 的 verifyAuthentication 返回 {"loggedIn": "true|false", "verified": "true|false"}。
        两者语义不同：verified=False 表示「无法判定」，verified=True 且 loggedIn=False
        才是明确的「未登录」。上层不得把 verified=False 当成失败后继续扫描。
        """
        try:
            body = self._call("POST", "/JSON/authentication/verifyAuthentication",
                              timeout_seconds=15.0, _reason=ZAP_REASON_PLUGIN_MISSING)
        except ZAPConnectorError as exc:
            if exc.reason == ZAP_REASON_PLUGIN_MISSING:
                return False, False
            raise
        if not isinstance(body, dict):
            return False, False
        return _as_bool(body.get("loggedIn")), _as_bool(body.get("verified"))

    def browser_session_established(self) -> tuple[bool, str]:
        """判断当前上下文是否具备「浏览器里的登录态」。

        依据是**已配置的 Session 管理方式**，不是页面实际是否登录——ZAP 没有读取
        浏览器登录态的 API。所以返回值必须和爬取结果一起看：

        - 返回 False 时，Web 爬取只能覆盖登录页，绝不能报「认证后的 Web 扫描完成」；
        - 返回 True 时，Worker 仍需比对 discovered URLs 里有没有命中 logged_in_indicator，
          两者都通过才算覆盖到了业务页面（§十二）。
        """
        method = self._session_method
        if method == "cookieBased" and self._has_session_value:
            return True, "浏览器会话已建立（cookieBased，会话值已导入）"
        if method == "cookieBased" and not self._has_session_value:
            return False, "已声明 cookieBased 会话但未提供会话值，浏览器无法登录"
        if method in ("headerBased", "headerCookieBased", "queryBased", "cookieBasedNameBased"):
            return False, "仅配置了请求级鉴权；浏览器渲染 SPA 时不会带上，前端页面仍会停在登录页"
        if self._auth_mode == AUTH_MODE_MANUAL:
            return False, "手动扫码登录需要人工浏览器交互；本部署未提供该能力，请改用 API Bearer Token 扫描"
        return False, "未配置浏览器可用的认证会话"

    # ------------------------------------------------------------------ OpenAPI

    def import_openapi(self, document: str, *, file_name: str = "openapi.json") -> dict[str, Any]:
        """导入 OpenAPI 3 文档。

        document 是**平台重建的** OpenAPI（见 openapi_export.py），不是用户原文——
        原文档中的 servers 字段可能指向未授权域名，导入前已在导出层剥离。
        """
        text = (document or "").strip()
        if not text:
            raise ZAPConnectorError("OpenAPI 文档为空", reason=ZAP_REASON_CONTEXT_FAILED)
        try:
            body = self._call(
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

    # ------------------------------------------------------------------ 爬取

    def start_spider(self, url: str, *, max_depth: int = 3, max_children: int = 10,
                     max_threads: int = 10, exclude_patterns: Iterable[str] = ()) -> dict[str, Any]:
        """启动传统 Spider。

        max_depth 截断到硬上限：传统 Spider 深度无上限会把整站拉进来。
        """
        self._assert_url_in_scope(url)
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
            result = self._call("POST", "/JSON/spider/spider", json_body=body, timeout_seconds=30.0)
        except ZAPConnectorError as exc:
            if exc.reason in (ZAP_REASON_PLUGIN_MISSING, ZAP_REASON_UNAVAILABLE):
                raise ZAPConnectorError("启动 Spider 失败", reason=ZAP_REASON_SPIDER_FAILED) from exc
            raise
        scan_ref = _string_of(result, "scan", result) if isinstance(result, dict) else str(result)
        if scan_ref and str(scan_ref).lstrip("-").isdigit() and int(str(scan_ref)) < 0:
            raise ZAPConnectorError("Spider 拒绝启动（目标不在扫描范围内）", reason=ZAP_REASON_SPIDER_FAILED)
        return {"scan_ref": str(scan_ref)}

    def start_client_spider(self, url: str, *, max_depth: int = 5, page_count: int = 0,
                            target_regex: str = "", user_agent_script: str = "") -> dict[str, Any]:
        """启动 Client Spider（真实浏览器渲染）。

        page_count=0 表示不限页面数——但受 max_depth 约束。
        user_agent_script 用于把 XSRF token 等写进前端请求。
        """
        self._assert_url_in_scope(url)
        depth = max(1, min(int(max_depth or 5), ACTIVE_DEPTH_HARD_CAP))
        try:
            self._call("POST", "/JSON/clientspider/setMaxCrawlDepth",
                       json_body={"maxCrawlDepth": depth}, timeout_seconds=10.0,
                       _reason=ZAP_REASON_PLUGIN_MISSING)
            if int(page_count or 0) > 0:
                self._call("POST", "/JSON/clientspider/setPageCount",
                           json_body={"pageCount": int(page_count)}, timeout_seconds=10.0,
                           _reason=ZAP_REASON_PLUGIN_MISSING)
            regex = (target_regex or "").strip()
            if regex:
                self._call("POST", "/JSON/clientspider/setTargetRegex",
                           json_body={"targetRegex": regex}, timeout_seconds=10.0,
                           _reason=ZAP_REASON_PLUGIN_MISSING)
            script = (user_agent_script or "").strip()
            if script:
                self._call("POST", "/JSON/authentication/setUserAgent", json_body={"script": script},
                           timeout_seconds=10.0)
            result = self._call("POST", "/JSON/clientspider/clientspider", json_body={"url": url},
                                timeout_seconds=30.0, _reason=ZAP_REASON_PLUGIN_MISSING)
        except ZAPConnectorError as exc:
            if exc.reason == ZAP_REASON_PLUGIN_MISSING:
                raise ZAPConnectorError(
                    "ZAP 不支持 Client Spider，无法爬取前端路由页面",
                    reason=ZAP_REASON_PLUGIN_MISSING,
                ) from exc
            raise
        return {"scan_ref": _string_of(result, "id", "") if isinstance(result, dict) else ""}

    # ------------------------------------------------------------------ 被动扫描

    def start_passive_scan(self) -> None:
        """触发被动扫描。

        ZAP 的被动扫描是自动的：请求一产生就分析。这个方法保留在接口上是为了
        让编排层显式表达「这一阶段开始了」，不做任何 ZAP 调用。
        """
        return None

    def wait_passive_scan(self, timeout_seconds: float = 120.0, poll_interval: float = 1.0) -> ZAPProgress:
        """等待被动扫描队列清空。

        超时不算失败——被动扫描是异步的，超时说明「还没扫完」，
        返回 running=True 让 Worker 决定是继续等还是判超时。

        Worker 应当传入较短的 timeout_seconds（如 30s），
        这样心跳与取消检查还能在两次调用之间执行。
        """
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        interval = max(0.05, float(poll_interval))
        progress = self._pscan_progress()
        while progress.running and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            time.sleep(min(interval, max(0.05, remaining)))
            progress = self._pscan_progress()
        return progress

    def list_passive_rules(self) -> list[dict[str, str]]:
        """列出当前生效的被动扫描规则清单（需求 §十四「查看实际扫描规则清单」）。"""
        try:
            body = self._call("POST", "/JSON/pscan/getActiveRules", timeout_seconds=10.0)
        except ZAPConnectorError:
            return []
        rules: list[dict[str, str]] = []
        if isinstance(body, dict):
            policy = body
        elif isinstance(body, list):
            policy = {str(item): {"description": ""} for item in body}
        else:
            return []
        for rule_id, meta in policy.items():
            description = str(meta.get("description") or "") if isinstance(meta, dict) else ""
            rules.append({"rule_id": str(rule_id), "description": description})
        return rules

    # ------------------------------------------------------------------ 主动扫描

    def start_active_scan(
        self,
        url: str,
        *,
        max_duration: int = 20,
        max_rule_duration: int = 10,
        max_concurrency: int = 5,
        request_delay_ms: int = 0,
        max_alerts_per_rule: int = 20,
        selected_rule_ids: Iterable[str] = (),
        excluded_paths: Iterable[str] = (),
        threshold: str = "default",
    ) -> str:
        """启动受控主动扫描，返回 ZAP scan id。

        所有参数都先过硬上限截断，再下发——**配置值永远不会被信任**。
        selected_rule_ids 为空表示沿用 ZAP 已启用规则；非空时只保留这些规则，
        其余全部关闭（§十五「禁止默认启用所有高强度规则」）。
        """
        self._assert_url_in_scope(url)
        # 攻击开关是运维侧的硬保险：一旦被关掉，平台不得自己改回去（§十五 / §三十四）。
        try:
            policy = self._call("POST", "/JSON/ascan/getAttackPolicy", timeout_seconds=10.0)
        except ZAPConnectorError:
            policy = None
        if isinstance(policy, dict) and not _as_bool(policy.get("attackEnabled")):
            raise ZAPConnectorError(
                "主动扫描已被禁用（attackEnabled=false），平台不会自动改回开启",
                reason=ZAP_REASON_ACTIVE_FAILED,
            )
        duration = max(1, min(int(max_duration or 20), ACTIVE_MAX_DURATION_HARD_CAP))
        rule_duration = max(1, min(int(max_rule_duration or 10), ACTIVE_MAX_RULE_DURATION_HARD_CAP))
        concurrency = max(1, min(int(max_concurrency or 1), ACTIVE_MAX_CONCURRENCY_HARD_CAP))
        delay = max(ACTIVE_MIN_REQUEST_DELAY_MS, min(int(request_delay_ms or 0), ACTIVE_MAX_REQUEST_DELAY_MS))
        per_rule = max(1, min(int(max_alerts_per_rule or 20), ACTIVE_MAX_ALERTS_PER_RULE_HARD_CAP))
        threshold = threshold if threshold in ("default", "low", "medium", "high") else "default"

        knobs = [
            ("POST", "/JSON/ascan/setMaxDurationInMinutes", {"maxDurationInMinutes": duration}),
            ("POST", "/JSON/ascan/setMaxRuleDurationInMinutes", {"maxRuleDurationInMinutes": rule_duration}),
            ("POST", "/JSON/ascan/setConcurrency", {"concurrency": concurrency}),
            ("POST", "/JSON/ascan/setRequestTimingInMs", {"requestTimingInMs": delay}),
            ("POST", "/JSON/ascan/setMaxAlertsPerRule", {"maxAlertsPerRule": per_rule}),
            ("POST", "/JSON/ascan/setDefaultRuleThreshold", {"threshold": threshold}),
            ("POST", "/JSON/ascan/enableAttack", {"state": 1}),
        ]
        excluded = [p for p in excluded_paths if p and p.strip()]
        if excluded:
            knobs.append(("POST", "/JSON/ascan/setAttackPolicy",
                          {"excludedPaths": "|".join(_escape_regex(p) for p in excluded[:100])}))

        try:
            for method, path, body in knobs:
                self._call(method, path, json_body=body, timeout_seconds=10.0)

            wanted = [str(r) for r in selected_rule_ids if r is not None and str(r).strip()]
            if wanted:
                # 只开选中的规则：先关掉全部，再逐个打开。
                for method, path, body in [
                    ("POST", "/JSON/ascan/enableAttack", {"state": 1}),
                ]:
                    self._call(method, path, json_body=body, timeout_seconds=10.0)
                try:
                    policy = self._call("POST", "/JSON/ascan/getAttackPolicy", timeout_seconds=10.0)
                    enabled = {
                        r.strip() for r in str(
                            policy.get("enabledRules") if isinstance(policy, dict) else ""
                        ).split(",") if r.strip()
                    }
                except ZAPConnectorError:
                    enabled = set()
                for rule_id in enabled - set(wanted):
                    self._call("POST", "/JSON/ascan/enableRule",
                               json_body={"ruleId": rule_id, "state": 0}, timeout_seconds=10.0)
                for rule_id in wanted:
                    self._call("POST", "/JSON/ascan/enableRule",
                               json_body={"ruleId": rule_id, "state": 1}, timeout_seconds=10.0)

            result = self._call("POST", "/JSON/ascan/scan", json_body={"url": url}, timeout_seconds=30.0)
        except ZAPConnectorError as exc:
            if exc.reason == ZAP_REASON_PLUGIN_MISSING:
                raise ZAPConnectorError(
                    "ZAP 缺少主动扫描组件，无法执行受控主动扫描",
                    reason=ZAP_REASON_ACTIVE_FAILED,
                ) from exc
            raise

        scan_id = _string_of(result, "scan", result) if isinstance(result, dict) else str(result)
        text = str(scan_id).strip()
        if not text or not text.lstrip("-").isdigit() or int(text) < 0:
            raise ZAPConnectorError(
                "主动扫描被 ZAP 拒绝（目标不在范围内或攻击已关闭）", reason=ZAP_REASON_ACTIVE_FAILED,
            )
        self._scan_ids.append(text)
        return text

    def set_active_scan_limits(self, *, max_duration: int = 20, max_rule_duration: int = 10,
                               max_concurrency: int = 5, request_delay_ms: int = 0) -> None:
        """单独设置主动扫描限额（供任务预热与审计核对用）。"""
        duration = max(1, min(int(max_duration or 20), ACTIVE_MAX_DURATION_HARD_CAP))
        rule_duration = max(1, min(int(max_rule_duration or 10), ACTIVE_MAX_RULE_DURATION_HARD_CAP))
        concurrency = max(1, min(int(max_concurrency or 1), ACTIVE_MAX_CONCURRENCY_HARD_CAP))
        delay = max(ACTIVE_MIN_REQUEST_DELAY_MS, min(int(request_delay_ms or 0), ACTIVE_MAX_REQUEST_DELAY_MS))
        self._call("POST", "/JSON/ascan/setMaxDurationInMinutes",
                   json_body={"maxDurationInMinutes": duration}, timeout_seconds=10.0)
        self._call("POST", "/JSON/ascan/setMaxRuleDurationInMinutes",
                   json_body={"maxRuleDurationInMinutes": rule_duration}, timeout_seconds=10.0)
        self._call("POST", "/JSON/ascan/setConcurrency", json_body={"concurrency": concurrency},
                   timeout_seconds=10.0)
        self._call("POST", "/JSON/ascan/setRequestTimingInMs",
                   json_body={"requestTimingInMs": delay}, timeout_seconds=10.0)

    # ------------------------------------------------------------------ 进度与停止

    def get_scan_progress(self, scan_ids: Iterable[str] = ()) -> ZAPProgress:
        """汇总当前所有阶段的进度。

        percentage 只在 ZAP 明确给出时才填；否则保持 None，
        由前端显示阶段 + 计数而不是虚构一个百分比（§十七）。
        """
        running = False
        alerts = 0
        pages = 0
        requests = 0
        urls = 0
        stages: list[str] = []

        # Spider
        try:
            body = self._call("POST", "/JSON/spider/isRunning", timeout_seconds=10.0)
            spider_running = _as_bool(body.get("Running")) if isinstance(body, dict) else False
        except ZAPConnectorError:
            spider_running = False
        if spider_running:
            running = True
            stages.append("Spider 爬取")

        # Client Spider（组件缺失时静默降级）
        try:
            body = self._call("POST", "/JSON/clientspider/isClientSpiderRunning", timeout_seconds=10.0)
            client_running = _as_bool(body.get("Running")) if isinstance(body, dict) else False
        except ZAPConnectorError:
            client_running = False
        if client_running:
            running = True
            stages.append("Client Spider 爬取")

        # 主动扫描
        percentages: list[int] = []
        for scan_id in [s for s in scan_ids if str(s).strip()]:
            try:
                body = self._call("GET", "/JSON/ascan/progress", params={"scanId": str(scan_id)},
                                  timeout_seconds=10.0)
            except ZAPConnectorError:
                continue
            if not isinstance(body, dict):
                continue
            # ascan/progress 对已完成的扫描仍然可读，所以要靠 Percentage 判断是否还在跑。
            percentage = _int_of(body.get("Percentage"))
            if percentage is None or percentage < 100:
                running = True
                stages.append("主动扫描")
            alerts = max(alerts, _int_of(body.get("Number of alerts")))
            requests = max(requests, _int_of(body.get("Number of requests")))
            pages = max(pages, _int_of(body.get("Number of processed URLs")))
            if percentage is not None:
                percentages.append(percentage)

        # 被动扫描
        try:
            pscan = self._pscan_progress()
            if pscan.running:
                running = True
                stages.append("被动扫描")
            alerts = max(alerts, pscan.alerts)
            requests = max(requests, pscan.requests)
            pages = max(pages, pscan.pages)
            urls = max(urls, pscan.urls)
        except ZAPConnectorError:
            pass

        # 百分比只在 ZAP 明确给出时才填；爬取阶段一律不虚构。
        percentage: int | None = None
        if percentages:
            percentage = int(round(sum(percentages) / len(percentages)))

        return ZAPProgress(
            running=running,
            percentage=percentage,
            stage=" / ".join(stages) if stages else "完成",
            pages=pages,
            requests=requests,
            alerts=alerts,
        )

    def stop_scan(self, scan_ids: Iterable[str] = ()) -> None:
        """停止所有运行中的扫描。逐条调用，任一失败不影响其余。"""
        ids = [str(s).strip() for s in scan_ids if str(s).strip()] or list(self._scan_ids)
        stopped: list[str] = []
        for scan_id in ids:
            try:
                self._call("POST", "/JSON/ascan/stopScan", timeout_seconds=10.0)
                stopped.append(f"ascan:{scan_id}")
            except ZAPConnectorError:
                continue
        for path, label in (
            ("/JSON/spider/stopSpider", "spider"),
            ("/JSON/clientspider/stopClientSpider", "clientspider"),
        ):
            try:
                self._call("POST", path, timeout_seconds=10.0)
                stopped.append(label)
            except ZAPConnectorError:
                continue
        self._scan_ids = []

    # ------------------------------------------------------------------ 结果

    def get_alerts(self, rule_ids: Iterable[str] = ()) -> list[ZAPAlert]:
        """拉取告警并转成平台结构。

        evidence / solution / attack 字段可能回显请求头里的凭据，
        在此处就地脱敏——不让原文进入事件表或 Finding（§二十一）。
        """
        body = self._call("POST", "/JSON/core/alertJson", timeout_seconds=30.0)
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

    def get_alert_counts(self, alerts: Iterable[ZAPAlert]) -> ZAPAlertCounts:
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

    def get_scan_statistics(self) -> tuple[ZAPPagesStats, ZAPAlertCounts]:
        """返回爬取统计与告警汇总。

        ZAP 在不同版本上 countAlerts / urls / history 可用性不一，
        任何一个失败都降级为 0 而不是抛错——统计缺失不能阻断结果导入。
        """
        pages = 0
        urls = 0
        requests = 0
        try:
            body = self._call("GET", "/JSON/core/urls", timeout_seconds=15.0)
            urls = len(body) if isinstance(body, list) else 0
        except ZAPConnectorError:
            pass
        try:
            body = self._call("POST", "/JSON/pscan/progress", timeout_seconds=15.0)
            if isinstance(body, dict):
                pages = _int_of(body.get("ScannedCount")) or pages
                requests = _int_of(body.get("QueuedUrls")) or requests
        except ZAPConnectorError:
            pass
        alerts = self.get_alerts()
        stats = ZAPPagesStats(pages=pages or urls, requests=requests, urls=urls)
        return stats, self.get_alert_counts(alerts)

    def list_urls(self) -> list[str]:
        """列出已发现的 URL（用于覆盖率统计）。端点不可用时返回空列表。

        URL 的凭据参数值在返回前抹掉——覆盖率行会入库。
        """
        try:
            body = self._call("GET", "/JSON/core/urls", timeout_seconds=15.0)
        except ZAPConnectorError:
            return []
        if not isinstance(body, list):
            return []
        return [redact_url(str(u)) for u in body]

    # ------------------------------------------------------------------ 底层调用

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: Any = None,
        timeout_seconds: float | None = None,
        _reason: str = ZAP_REASON_BAD_RESPONSE,
    ) -> Any:
        """发一次 ZAP 请求并把传输层错误映射成 Connector 错误。"""
        effective_timeout = timeout_seconds if timeout_seconds is not None else self._timeout
        try:
            return self._transport.request(
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

    def _pscan_progress(self) -> ZAPProgress:
        """读被动扫描进度。"""
        body = self._call("POST", "/JSON/pscan/progress", timeout_seconds=15.0)
        if not isinstance(body, dict):
            return ZAPProgress(running=False)
        return ZAPProgress(
            running=_as_bool(body.get("Running")) or _int_of(body.get("QueueSize")) > 0,
            percentage=None,
            stage="被动扫描",
            pages=_int_of(body.get("ScannedCount")) or 0,
            requests=_int_of(body.get("QueuedUrls")) or 0,
            alerts=_int_of(body.get("Alerts")) or 0,
            urls=len(body.get("ScannedUrls") or []),
        )

    def close(self) -> None:
        """关闭底层传输。幂等。"""
        self._transport.close()


# --------------------------------------------------------------------------- 内部工具


def map_alert_severity(risk: str) -> str:
    """延迟导入避免模块级循环。"""
    from app.features.security_testing.zap.contracts import map_zap_risk

    return map_zap_risk(risk)


def _describe(message: str, *, path: str) -> str:
    """把传输层消息变成带路径上下文的中文说明，去掉内部字段名。"""
    text = (message or "ZAP 请求失败").strip()
    return f"{text}（{path}）" if path and path not in text else text


def _map_reason(exc: ZAPTransportError, *, default: str) -> str:
    """传输层状态码 → Connector 错误原因。"""
    if exc.status_code is None:
        return ZAP_REASON_UNAVAILABLE
    if exc.status_code in (401, 403):
        return ZAP_REASON_API_AUTH_FAILED
    if exc.status_code == 404:
        # 404 可能是「组件不存在」也可能是「该 URL 不在扫描范围内」。
        # 用 default 区分：调用方知道自己期望的是哪个能力。
        return ZAP_REASON_PLUGIN_MISSING if default != ZAP_REASON_BAD_RESPONSE else ZAP_REASON_BAD_RESPONSE
    return default


def _as_bool(value: Any) -> bool:
    """ZAP 的布尔值经常是字符串 "true" / 0 / 1。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return int(value) != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "on"}
    return False


def _int_of(value: Any) -> int | None:
    """尽力转 int；失败返回 None 而不是 0（区分「未知」与「真的是 0」）。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _string_of(body: dict[str, Any], key: str, fallback: Any = "") -> Any:
    """取一个字段；缺失时返回 fallback。"""
    value = body.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        return fallback
    return value


def _auth_detail(session_method: str, authenticated: bool, verified: bool) -> str:
    """生成一句可审计的中文说明，不含任何凭据值。"""
    if session_method in ("none", ""):
        return "未配置认证"
    if not verified:
        return f"认证状态无法判定（Session 管理方式：{session_method}）"
    if authenticated:
        return f"已验证登录成功（Session 管理方式：{session_method}）"
    return f"已验证但登录失败（Session 管理方式：{session_method}）"


def _escape_regex(text: str) -> str:
    """把路径转成安全的正则片段。

    不做转义就是把用户输入的路径当成 ZAP 的正则执行——一次前缀匹配的排除
    路径就能让整站被排除（或反过来把不该扫的扫进来）。
    """
    return re.escape((text or "").strip().lstrip("/"))


def _to_regex(base_url: str, path: str) -> str:
    """把 (base_url, path) 合成一条 ZAP 可用的范围正则。"""
    parts = urlsplit(base_url)
    host = re.escape(parts.netloc)
    base = r"https?://" + host
    needle = re.escape((path or "").strip().lstrip("/"))
    return base + "/" + needle if needle else base
