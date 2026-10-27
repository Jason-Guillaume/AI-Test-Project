"""Mock ZAP：一个进程内的 ZAP API 模拟器。

它的作用不是"假装 ZAP 存在"，而是**可验证地覆盖真实扫描的语义**：
- 只接受 scope 内的 URL（越界请求不会生成任何告警）；
- 传统 Spider 发现不了 ``spa_only`` 的路由，只有 Client Spider 能发现；
- ``login_required`` 的页面在浏览器登录态未建立时不会访问，只会命中登录页；
- 主动扫描只跑被启用的规则，且遵守排除路径 / 单规则最大时长 / 告警上限；
- 凭据类告警（cookie 未加 HttpOnly 等）只在真正有请求产生时才出现。

单元测试验证的是 Connector + 编排 + 归一化这一整条链路的行为，
而不是对 ZAP 某个字段名做字符串匹配。真实环境的差距由 integration_check
（需要 Docker + ZAP 容器）验证，见 docs/zap/。

不模拟的内容（诚实声明）：
- ZAP 自身的进程生命周期、浏览器二进制下载、代理端口转发；
- 真实的 HTTP 流量——它从不发任何出站请求。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

from app.features.security_testing.zap.transport import ZAPTransportError

# --------------------------------------------------------------------------- 模拟素材


@dataclass(slots=True)
class MockRule:
    """一条模拟扫描规则。

    risk / confidence 用 ZAP 的原始取值（Risk 是英文文本，Confidence 是 1-5），
    刻意不与平台 Severity 混用——映射发生在 normalizer。
    """

    rule_id: int
    name: str
    risk: str
    confidence: int
    category: str = "both"  # 扫描模式：pscan / ascan / both
    reference: str = "https://owasp.org/www-project-top-ten/"
    enabled: bool = True


@dataclass(slots=True)
class MockEndpoint:
    """一个被模拟的 HTTP 端点。"""

    path: str
    methods: list[str] = field(default_factory=lambda: ["GET"])
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    query_params: list[str] = field(default_factory=list)
    body_params: list[str] = field(default_factory=list)
    passive_rule_ids: list[int] = field(default_factory=list)
    active_rule_ids: list[int] = field(default_factory=list)
    # 只有 Client Spider（真实浏览器渲染）才能发现的 SPA 路由。
    spa_only: bool = False
    # 需要登录后才能访问的业务页面。
    login_required: bool = False
    # 页面里会发起 XHR/Fetch 的请求（Client Spider 才会采集）。
    xhr_targets: list[str] = field(default_factory=list)


#: 一套贴近真实 ZAP 的规则清单（规则号与名称取自 ZAP 默认规则集）。
DEFAULT_MOCK_RULES: list[MockRule] = [
    MockRule(10010, "Cookie Without 'HttpOnly' Flag", "Low", 3, "pscan"),
    MockRule(10012, "Cookie Without 'Secure' Flag", "Low", 3, "pscan"),
    MockRule(10015, "Anti-clickjacking Header 'X-Frame-Options' Missing", "Medium", 4, "pscan"),
    MockRule(10020, "Server Leaks Version Information via 'X-Powered-By' HTTP Response Header", "Informational", 5, "pscan"),
    MockRule(10021, "Server Leaks Version Information via 'Server' HTTP Response Header", "Informational", 5, "pscan"),
    MockRule(10023, "Character Encoding Warnings", "Low", 3, "pscan"),
    MockRule(10035, "Content Security Policy (CSP) Header Not Set", "Medium", 4, "pscan"),
    MockRule(10036, "Strict-Transport-Security (HSTS) Header Not Set", "Medium", 4, "pscan"),
    MockRule(10038, "Cookie Without SameSite Attribute", "Medium", 3, "pscan"),
    MockRule(10095, "Potential Remote Code Execution via XML External Entity Injection (XXE)", "High", 3, "both"),
    MockRule(20012, "Content Security Policy (CSP) Information Disclosure", "Medium", 4, "pscan"),
    MockRule(30001, "Path Traversal", "High", 4, "ascan"),
    MockRule(40004, "DOM Based Cross Site Scripting", "Medium", 4, "pscan"),
    MockRule(40013, "Loosely Scoped Cookie", "Medium", 3, "pscan"),
    MockRule(40018, "Missing Anti-CSRF Tokens", "Low", 3, "pscan"),
    MockRule(40029, "Possible Open Redirect Vulnerability", "Medium", 3, "pscan"),
    MockRule(60001, "SQL Injection", "High", 3, "ascan"),
    MockRule(60002, "SQL Injection - Oracle", "High", 3, "ascan"),
    MockRule(60103, "Cross Site Scripting (Reflected)", "Medium", 4, "ascan"),
    MockRule(60106, "Cross Site Scripting (Persistent)", "High", 3, "ascan"),
    MockRule(60213, "User-Agent Bypasses WAF/IPS", "Low", 3, "ascan"),
    MockRule(90022, "Cross Domain Misconfiguration", "Medium", 4, "pscan"),
]

#: 登录页：未登录时 Client Spider 只能到这里为止。
LOGIN_PATH = "/login"


def _default_world(endpoints: list[MockEndpoint] | None = None) -> list[MockEndpoint]:
    """一套可复现的示例被测应用（用于单测与冒烟）。"""
    return endpoints or [
        MockEndpoint(
            LOGIN_PATH,
            headers={"Set-Cookie": "session=abc; Path=/", "X-Powered-By": "Express"},
            passive_rule_ids=[10020, 10010, 10012, 40013],
        ),
        MockEndpoint(
            "/",
            headers={"Set-Cookie": "session=abc; Path=/; Secure"},
            passive_rule_ids=[10015, 10035, 10036, 10038, 10095, 40018],
        ),
        MockEndpoint(
            "/users",
            methods=["GET", "POST"],
            headers={"Content-Type": "application/json"},
            query_params=["page"],
            body_params=["name"],
            passive_rule_ids=[10035, 10036, 40018],
            active_rule_ids=[60001, 60103],
        ),
        MockEndpoint(
            "/users/{id}",
            methods=["GET", "PATCH"],
            query_params=["id"],
            passive_rule_ids=[40029],
            active_rule_ids=[30001, 60103],
        ),
        MockEndpoint(
            "/reports",
            query_params=["q"],
            active_rule_ids=[30001],
        ),
        # SPA 路由：传统 Spider 发现不了，只有 Client Spider 能到。
        MockEndpoint(
            "/app/dashboard",
            spa_only=True,
            login_required=True,
            passive_rule_ids=[10015, 10035, 40004],
            xhr_targets=["/api/v1/dashboard"],
        ),
        MockEndpoint(
            "/app/orders",
            spa_only=True,
            login_required=True,
            query_params=["page"],
            passive_rule_ids=[40004, 10038],
            active_rule_ids=[60103],
        ),
        MockEndpoint(
            "/api/v1/dashboard",
            methods=["GET"],
            spa_only=True,
            login_required=True,
            passive_rule_ids=[10035],
            active_rule_ids=[60001],
        ),
        MockEndpoint(
            "/api/v1/users/me",
            methods=["GET"],
            login_required=True,
            headers={"Content-Type": "application/json"},
            passive_rule_ids=[10036],
        ),
    ]


class MockZAPWorld:
    """被模拟的被测应用 + ZAP 实例配置。"""

    def __init__(
        self,
        *,
        base_host: str = "https://test.example.com",
        version: str = "2.16.0",
        add_ons: list[dict[str, str]] | None = None,
        endpoints: list[MockEndpoint] | None = None,
        rules: list[MockRule] | None = None,
        has_scannerpool: bool = False,
        has_ajax_spider: bool = False,
        has_client_spider: bool = True,
        has_openapi: bool = True,
        simulate_hang: bool = False,
    ) -> None:
        """初始化模拟世界。"""
        self.base_host = base_host.strip().rstrip("/")
        self.version = version
        self.add_ons = add_ons if add_ons is not None else [
            {"name": "clientSpider", "version": "2.4.0"},
            {"name": "activeScan", "version": "1.25.0"},
            {"name": "passiveScan", "version": "2.3.0"},
            {"name": "openapi", "version": "2.1.0"},
            {"name": "authhelper", "version": "0.13.0"},
        ]
        self.endpoints = endpoints if endpoints is not None else _default_world()
        self.rules = rules if rules is not None else list(DEFAULT_MOCK_RULES)
        self.has_scannerpool = has_scannerpool
        self.has_ajax_spider = has_ajax_spider
        self.has_client_spider = has_client_spider
        self.has_openapi = has_openapi
        # 挂起模拟：让爬取/主动扫描一直跑，用于超时与取消测试。
        self.simulate_hang = simulate_hang


#: 凭据类查询参数：出现在 URL 里会被告警回显，必须脱敏。
_CREDENTIAL_QUERY_KEYS = frozenset(
    {"token", "access_token", "refresh_token", "jwt", "api_key", "apikey", "session", "sid"}
)

#: 模拟真实 ZAP 回显 JWT 用：告警 URL 里会带上这个值，用来验证脱敏链路真的生效。
MOCK_TOKEN_VALUE = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJtb2NrIn0.mock-signature"


def _sample_query_value(param: str) -> str:
    """给一个查询参数造一个样本值；凭据参数用 JWT 形态，其余用占位值。"""
    return MOCK_TOKEN_VALUE if param.lower() in _CREDENTIAL_QUERY_KEYS else "v1"


def _with_sample_query(url: str, params: list[str]) -> str:
    """把示例查询参数拼到 URL 上（真实 ZAP 会在告警里回显实际扫描过的 URL）。"""
    if not params:
        return url
    query = "&".join(f"{p}={_sample_query_value(p)}" for p in params)
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{query}"


class MockZAPTransport:
    """实现 ZAPTransport 协议的模拟器。

    状态说明：
    - ``_alerts``：已产生的告警（ZAP 原始 JSON 形态）；
    - ``_history``：已产生的请求记录（用于统计请求数与已响应端点）；
    - ``_urls``：已发现 URL；
    - ``_scope`` / ``_excluded``：扫描范围；
    - ``browser_logged_in``：派生属性，浏览器里是否真的建立了登录态。
    """

    def __init__(self, world: MockZAPWorld | None = None, *, fail_with: int | None = None) -> None:
        """初始化。

        Args:
            world: 模拟世界；缺省用内置示例应用。
            fail_with: 非空时所有请求都返回该 HTTP 状态码（模拟鉴权失败 / 不可达）。
        """
        self.world = world or MockZAPWorld()
        self.fail_with = fail_with
        self.closed = False

        # 范围
        self.in_scope: list[str] = []
        self.in_scope_prefix: list[str] = []
        self.in_scope_regex: list[str] = []
        self.out_of_scope: list[str] = []
        self.excluded_regex: list[str] = []
        self.scan_out_of_scope: bool = False

        # 认证与 Session
        self.auth_method: str = "none"
        self.auth_strategy: str = "manual"
        self.logged_in_indicator: str = ""
        self.logged_out_indicator: str = ""
        self.user_agent_script: str = ""
        self.session_method: str = "none"
        self.session_name: str = ""
        self.session_header: str = ""
        self.session_value: str = ""
        self.session_token_name: str = ""

        # 浏览器会话历史（不是状态位——状态由 browser_logged_in 派生）
        self.browser_pages_visited: list[str] = []
        self._spider_pages: list[str] = []
        self._browser_logged_in_override: bool | None = None

        # 规则开关
        self.pscan_enabled: set[str] = {
            str(rule.rule_id) for rule in self.world.rules if rule.enabled and rule.category in {"pscan", "both"}
        }
        self.ascan_enabled: set[str] = {
            str(rule.rule_id) for rule in self.world.rules if rule.enabled and rule.category in {"ascan", "both"}
        }
        self.pscan_policies: dict[str, dict] = {}
        self.pscan_mode: str = "minimum"
        self.attack_policy: dict[str, Any] = {
            "threshold": "default",
            "excludedPaths": "",
            "excludedMimeTypes": "",
            "attackEnabled": True,
            "maxDurationInMinutes": 20,
            "requestTimingInMs": 0,
            "maxRuleDurationInMinutes": 30,
            "disableForLocalAddresses": True,
            "enabledRules": ",".join(sorted(self.ascan_enabled)),
        }
        self.scan_policy: dict[str, Any] = {"name": "Default", "maxAlertsPerRule": 10}

        # 扫描运行状态
        self.spider_running: bool = False
        self.client_spider_running: bool = False
        # ZAP 的 setPageCount 语义是「最多爬多少页」，0 = 不限。
        self.client_spider_page_limit: int = 0
        self.client_spider_max_depth: int = 5
        self.client_spider_target_regex: str = ""
        self.active_scan_running: bool = False
        self.active_scan_ids: list[str] = []
        self.active_scan_progress: dict[str, dict] = {}
        self.pscan_queued: int = 0
        self.openapi_imports: list[dict] = []

        # 结果
        self._alerts: list[dict] = []
        self._history: list[dict] = []
        self._urls: set[str] = set()
        self._pages: set[str] = set()
        self._alert_seq: int = 0
        self._scan_seq: int = 0
        self._requests_made: int = 0
        self._cancelled: bool = False

    # ------------------------------------------------------------------ 工具

    @staticmethod
    def _rule_map(world: MockZAPWorld) -> dict[int, MockRule]:
        """构建规则映射表。"""
        return {rule.rule_id: rule for rule in world.rules}

    def _split(self, url: str) -> tuple[str, str]:
        """拆出 host 与 path（含 query）。"""
        parts = urlsplit(url.strip() or self.world.base_host)
        netloc = parts.netloc
        if not netloc:
            netloc = urlsplit(self.world.base_host).netloc
        path = parts.path or "/"
        if parts.query:
            path = f"{path}?{parts.query}"
        return netloc, path

    def _host_of(self, url: str) -> str:
        """提取主机信息。"""
        return self._split(url)[0]

    def _path_of(self, url: str) -> str:
        """提取路径信息。"""
        return self._split(url)[1]

    def is_in_scope(self, url: str) -> bool:
        """是否落在受控扫描范围内。空范围 = 不限制（ZAP 语义）。"""
        host, path = self._split(url)
        if not self.in_scope and not self.in_scope_prefix and not self.in_scope_regex:
            return True
        if host in self.in_scope:
            return True
        for prefix in self.in_scope_prefix:
            if host == prefix.rstrip("*") or host.endswith("." + prefix.rstrip("/*")):
                return True
        for pattern in self.in_scope_regex:
            try:
                if re.search(pattern, url):
                    return True
            except re.error:
                continue
        return False

    def is_excluded(self, url: str) -> bool:
        """是否被排除在扫描之外（危险路径）。"""
        if self.scan_out_of_scope and self.out_of_scope:
            host, _ = self._split(url)
            if host in self.out_of_scope:
                return True
        path = self._path_of(url)
        for pattern in self.excluded_regex:
            try:
                if re.search(pattern, path):
                    return True
            except re.error:
                continue
        # 主动扫描策略里的 excludedPaths（分号分隔）。
        for item in str(self.attack_policy.get("excludedPaths") or "").split(";"):
            needle = item.strip()
            if needle and (needle in path):
                return True
        return False

    def _matches_endpoint(self, path: str) -> MockEndpoint | None:
        """按 path 找端点，支持 {id} 占位符。"""
        clean = path.split("?", 1)[0]
        for endpoint in self.world.endpoints:
            if endpoint.path == clean:
                return endpoint
            if "{" in endpoint.path:
                pattern = re.sub(r"\{[^}]+\}", r"[^/]+", endpoint.path)
                if re.fullmatch(pattern, clean):
                    return endpoint
        return None

    def _scrub_url(self, url: str) -> str:
        """把 URL query 里的凭据参数值抹掉（模拟真实响应不回显值）。"""
        parts = urlsplit(url)
        pairs = []
        for key, value in re.findall(r"([^=&?]+)=([^=&?]*)", parts.query):
            pairs.append((key, "******" if key.lower() in _CREDENTIAL_QUERY_KEYS else value))
        query = "&".join(f"{k}={v}" for k, v in pairs)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))

    def _emit_alert(
        self,
        rule: MockRule,
        url: str,
        *,
        method: str = "GET",
        parameter: str = "",
        evidence: str = "",
        attack: str = "",
    ) -> None:
        """产生一条告警（ZAP 原始 JSON 形态）。"""
        self._alert_seq += 1
        parts = urlsplit(url)
        self._alerts.append(
            {
                "id": str(rule.rule_id),
                "alert": rule.name,
                "name": rule.name,
                "risk": rule.risk,
                "confidence": str(rule.confidence),
                "url": self._scrub_url(url),
                "method": method,
                "param": parameter,
                "attack": attack,
                "evidence": evidence,
                "solution": rule.name,
                "reference": rule.reference,
                "cweId": str(_CWE_BY_RULE.get(rule.rule_id, 0)),
                "wascId": str(_WASC_BY_RULE.get(rule.rule_id, 0)),
                "date": "2026-10-19 12:00:00",
                "rise": "1",
                "extra": "",
                "sourceid": str(self._alert_seq),
            }
        )

    def seed_raw_alert(self, raw: dict[str, Any]) -> dict[str, Any]:
        """测试用：注入一条已构建好的 ZAP 原始形态告警。

        用于验证 Connector 的字段映射与脱敏，而不依赖 MockRule 表。
        """
        self._alert_seq += 1
        alert = dict(raw)
        alert.setdefault("id", "0")
        alert.setdefault("alert", alert.get("name") or f"未命名规则 {alert.get('id')}")
        alert.setdefault("risk", "Medium")
        alert.setdefault("confidence", "3")
        alert.setdefault("method", "GET")
        alert["sourceid"] = str(self._alert_seq)
        self._alerts.append(alert)
        return alert

    def _make_request(self, url: str, method: str) -> int:
        """模拟一次真实 HTTP 请求：记 history、跑被动规则。

        查询参数会带上样本值——真实 ZAP 会在告警 URL 里回显实际请求过的地址，
        所以这里必须真的造出 ``?token=...``，否则脱敏链路的测试没有意义。
        """
        if "?" not in url:
            endpoint_probe = self._matches_endpoint(self._split(url)[1])
            params = endpoint_probe.query_params if endpoint_probe else []
            if params:
                url = _with_sample_query(url, params)
        path = self._split(url)[1]
        if not self.is_in_scope(url):
            return 0
        if self.is_excluded(url):
            return 0
        endpoint = self._matches_endpoint(path)
        status = endpoint.status_code if endpoint else 404
        self._requests_made += 1
        self._urls.add(url)
        self._history.append(
            {
                "id": self._requests_made,
                "seqnum": self._requests_made,
                "request": f"{method} {url}",
                "response": f"HTTP/{status}",
                "method": method,
                "url": url,
                "responseCode": str(status),
                "responseBody": "{}",
                "cookie": "session=abc" if "Set-Cookie" in (endpoint.headers if endpoint else {}) else "",
            }
        )
        # 被动规则：所有请求都会触发命中的被动规则。
        if endpoint:
            for rule_id in endpoint.passive_rule_ids:
                rule = self._rule_map(self.world).get(rule_id)
                if rule and str(rule.rule_id) in self.pscan_enabled:
                    self._emit_alert(rule, url, method=method)
        self.pscan_queued += 1
        return status

    @property
    def browser_logged_in(self) -> bool:
        """浏览器上下文里是否真的存在登录态。

        只配 Authorization Header 不算：那是给 API 请求附加请求头的方式，
        浏览器渲染 SPA 时并不会带上（§十二）。两种情况才算：
        1. cookieBased Session 且给了值（对应浏览器登录 / 会话导入）；
        2. 测试用 override（对应 §十三 人工扫码后的浏览器登录）。
        """
        if self._browser_logged_in_override is not None:
            return self._browser_logged_in_override
        return self.session_method == "cookieBased" and bool((self.session_value or "").strip())

    def set_browser_login(self, logged_in: bool) -> None:
        """测试/人工登录入口：模拟扫码后浏览器里已经有会话。"""
        self._browser_logged_in_override = bool(logged_in)

    # ------------------------------------------------------------------ 主入口

    def request(
        self,
        *,
        method: str,
        path: str,
        params: Mapping[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """按 ZAP REST API 语义分发。"""
        if self.closed:
            raise ZAPTransportError("传输层已关闭", method=method, path=path)
        if self.fail_with is not None:
            raise ZAPTransportError(
                f"ZAP 返回 HTTP {self.fail_with}", status_code=self.fail_with, method=method, path=path,
            )

        handler = _HANDLERS.get((method.upper(), path))
        if handler is None:
            raise ZAPTransportError(
                f"Mock ZAP 未实现端点：{method.upper()} {path}", status_code=404, method=method, path=path,
            )
        return handler(self, params or {}, json_body or {}, files or {})

    def close(self) -> None:
        """标记关闭。"""
        self.closed = True


# --------------------------------------------------------------------------- 端点处理


def _about(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """构造 ZAP 版本与服务信息响应。"""
    return {
        "name": "OWASP ZAP",
        "version": self.world.version,
        "description": "OWASP ZAP - Zed Attack Proxy",
        "addOns": list(self.world.add_ons),
    }


def _core_version(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """返回模拟 ZAP 核心组件版本。"""
    return {"ZAP": self.world.version}


def _set_in_scope(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置`in`范围。"""
    self.in_scope.append((b.get("host") or "").rstrip("/"))
    return {"host": b.get("host", "")}


def _set_in_scope_prefix(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置`in`范围`prefix`。"""
    self.in_scope_prefix.append((b.get("host") or "").rstrip("/"))
    return {"host": b.get("host", "")}


def _set_in_scope_regex(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置`in`范围`regex`。"""
    self.in_scope_regex.append(b.get("regex") or "")
    return {"regex": b.get("regex", "")}


def _set_out_of_scope(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置`out``of`范围。"""
    self.out_of_scope.append((b.get("host") or "").rstrip("/"))
    return {"host": b.get("host", "")}


def _set_excluded(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置`excluded`。"""
    self.excluded_regex.append(b.get("regex") or "")
    return {"regex": b.get("regex", "")}


def _set_scan_out_of_scope(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置扫描`out``of`范围。"""
    self.scan_out_of_scope = bool(int(b.get("value") or 0))
    return {"value": str(int(b.get("value") or 0))}


def _spider(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """传统 Spider：只解析 HTML 链接，发现不了 spa_only 路由与登录后的页面。

    ZAP 的 maxDepth 是「链接层级」而不是「页数」，示例端点都在第 1 层，
    所以深度 >=1 时全部可达；这里只记录深度不做页面上限。
    """
    url = b.get("url") or self.world.base_host + "/"
    if not self.is_in_scope(url):
        return {"scan": "-1"}
    max_depth = min(int(b.get("maxDepth") or 3), 8)
    if max_depth < 1:
        return {"scan": "-1"}
    self.spider_running = True
    self._pages.add(url)
    try:
        for endpoint in self.world.endpoints:
            if endpoint.spa_only:
                continue  # 传统 Spider 不执行 JS，发现不了 SPA 路由
            if endpoint.login_required:
                continue  # 未登录时传统 Spider 只会停在登录页
            _visit(self, self.world.base_host + endpoint.path, endpoint, self._spider_pages)
    finally:
        if not self.world.simulate_hang:
            self.spider_running = False
    return {"scan": "1"}


def _stop_spider(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """停止爬虫。"""
    self.spider_running = False
    self._cancelled = True
    return {"Running": "false"}


def _spider_is_running(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """判断爬虫任务是否正在运行。"""
    return {"Running": "true" if self.spider_running else "false"}


def _client_spider(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """Client Spider：真实浏览器渲染，能发现 SPA 路由与 XHR。

    关键语义：**登录态必须在浏览器里真的存在**。只配了 Authorization 头不算——
    那是 API 请求附加头的方式，浏览器渲染 SPA 时不会带上（§十二）。
    """
    url = b.get("url") or self.world.base_host + "/"
    if not self.is_in_scope(url):
        return {"status": -1}
    if not self.world.has_client_spider:
        raise ZAPTransportError("Client Spider 组件不可用", status_code=404)
    self.client_spider_running = True
    self._pages.add(url)
    max_depth = min(int(self.client_spider_max_depth or 5), 8)
    page_limit = self.client_spider_page_limit
    target_regex = self.client_spider_target_regex

    def _crawl(target: str, endpoint: MockEndpoint | None, depth: int) -> None:
        """访问一个页面；depth 从 1 开始，XHR 展开算第 2 层。"""
        nonlocal pages
        if page_limit and pages >= page_limit:
            return
        if depth > max_depth:
            return
        if target_regex and not re.search(target_regex, target):
            return
        _visit(self, target, endpoint, self.browser_pages_visited)
        pages += 1
        if depth >= 2 or endpoint is None:
            return
        for xhr in endpoint.xhr_targets:
            _crawl(self.world.base_host + xhr, self._matches_endpoint(xhr), depth + 1)

    try:
        pages = 0
        for endpoint in self.world.endpoints:
            # 传统 Spider 已经覆盖的普通页面，Client Spider 不重复访问。
            if not endpoint.spa_only and not endpoint.login_required:
                continue
            if endpoint.login_required and not self.browser_logged_in:
                # 未登录：只能停在登录页，业务路由全部不可达（§十二）。
                continue
            _crawl(self.world.base_host + endpoint.path, endpoint, 1)
    finally:
        if not self.world.simulate_hang:
            self.client_spider_running = False
    return {"status": 1, "id": str(len(self.browser_pages_visited))}


def _visit(self: MockZAPTransport, target: str, endpoint: MockEndpoint | None, bucket: list[str]) -> None:
    """访问一个页面：记入调用方的页面清单并按方法发出请求。"""
    bucket.append(target)
    if endpoint is None:
        return
    for method in endpoint.methods:
        if self._make_request(target, method) == 404:
            self._urls.discard(target)



def _stop_client_spider(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """停止客户端爬虫。"""
    self.client_spider_running = False
    self._cancelled = True
    return {"Running": "false"}


def _client_spider_is_running(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """判断客户端爬虫任务是否正在运行。"""
    return {"Running": "true" if self.client_spider_running else "false"}


def _client_spider_set_depth(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置客户端爬虫深度。"""
    self.client_spider_max_depth = int(b.get("maxCrawlDepth") or 5)
    return {"maxCrawlDepth": str(self.client_spider_max_depth)}


def _client_spider_set_pages(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置客户端爬虫页面。"""
    self.client_spider_page_limit = max(0, int(b.get("pageCount") or 0))
    return {"pageCount": str(self.client_spider_page_limit)}


def _client_spider_set_regex(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置客户端爬虫正则表达式。"""
    self.client_spider_target_regex = b.get("targetRegex") or ""
    return {"targetRegex": self.client_spider_target_regex}


def _client_spider_set_state(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置客户端爬虫状态。"""
    return {"maxCrawlState": b.get("maxCrawlState") or "0"}


def _pscan_get_rules(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> list:
    """获取被动扫描规则。"""
    return sorted(self.pscan_enabled)


def _pscan_get_policy(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """获取被动扫描策略。"""
    return {
        str(rule.rule_id): {
            "description": rule.name,
            "rules": [str(rule.rule_id)],
        }
        for rule in self.world.rules
        if rule.category in {"pscan", "both"} and str(rule.rule_id) in self.pscan_enabled
    }


def _pscan_get_mode(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """获取被动扫描模式。"""
    return {"mode": self.pscan_mode}


def _pscan_set_mode(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置被动扫描模式。"""
    self.pscan_mode = b.get("mode") or "minimum"
    return {"mode": self.pscan_mode}


def _pscan_set_alert(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置被动扫描告警。"""
    rule_id = str(b.get("ruleId") or "")
    state = bool(int(b.get("state") or 0))
    if state:
        self.pscan_enabled.add(rule_id)
    else:
        self.pscan_enabled.discard(rule_id)
    return {"ruleId": rule_id, "state": "true" if state else "false"}


def _pscan_is_alert(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """判断被动扫描结果是否需要生成告警。"""
    rule_id = str(b.get("ruleId") or "")
    return {"alert": "true" if rule_id in self.pscan_enabled else "false"}


def _pscan_wait(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """等待被动扫描队列清空。挂起模拟下不返回（由调用方超时保护）。"""
    if self.world.simulate_hang:
        self.pscan_queued = max(self.pscan_queued, 1)
        return {"Completed": "false", "QueueSize": str(self.pscan_queued)}
    self.pscan_queued = 0
    return {"Completed": "true", "QueueSize": "0"}


def _pscan_progress(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """被动扫描进度。

    队列消化是异步的：没有抓取/扫描在跑时，队列视为已清空。
    ``simulate_hang`` 下保持有积压，用于验证等待超时。
    """
    if self.pscan_queued > 0 and not self.world.simulate_hang and not (
        self.spider_running or self.client_spider_running or self.active_scan_running
    ):
        self.pscan_queued = 0
    return {
        "ActiveAlerts": [],
        "Alerts": str(len(self._alerts)),
        "QueuedUrls": str(self.pscan_queued),
        "QueueSize": str(self.pscan_queued),
        "Running": "true" if (self.pscan_queued > 0 or self.spider_running or self.client_spider_running) else "false",
        "ScannedUrls": sorted(self._urls),
        "ScannedCount": str(len(self._urls)),
    }


def _ascan_get_policy(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """获取主动扫描策略。"""
    return dict(self.attack_policy)


def _ascan_set_policy(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置主动扫描策略。"""
    self.attack_policy.update({k: v for k, v in b.items() if k in self.attack_policy})
    return dict(self.attack_policy)


def _ascan_get_scan_policy(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """获取主动扫描`scan`策略。"""
    return dict(self.scan_policy)


def _ascan_set_scan_policy(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置主动扫描`scan`策略。"""
    self.scan_policy.update(b)
    return dict(self.scan_policy)


def _ascan_set_concurrency(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置主动扫描`concurrency`。"""
    self.attack_policy["concurrency"] = str(int(b.get("concurrency") or 1))
    return {"concurrency": self.attack_policy["concurrency"]}


def _ascan_set_timing(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置主动扫描时间参数。"""
    self.attack_policy["requestTimingInMs"] = int(b.get("requestTimingInMs") or 0)
    return {"requestTimingInMs": str(self.attack_policy["requestTimingInMs"])}


def _ascan_set_max_duration(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置主动扫描最大时长。"""
    self.attack_policy["maxDurationInMinutes"] = int(b.get("maxDurationInMinutes") or 0)
    return {"maxDurationInMinutes": str(self.attack_policy["maxDurationInMinutes"])}


def _ascan_set_max_rule_duration(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置主动扫描最大规则时长。"""
    self.attack_policy["maxRuleDurationInMinutes"] = int(b.get("maxRuleDurationInMinutes") or 0)
    return {"maxRuleDurationInMinutes": str(self.attack_policy["maxRuleDurationInMinutes"])}


def _ascan_set_max_alerts(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置主动扫描最大告警。"""
    self.scan_policy["maxAlertsPerRule"] = int(b.get("maxAlertsPerRule") or 10)
    return {"maxAlertsPerRule": str(self.scan_policy["maxAlertsPerRule"])}


def _ascan_set_threshold(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置主动扫描阈值。"""
    self.attack_policy["threshold"] = b.get("threshold") or "default"
    return {"threshold": self.attack_policy["threshold"]}


def _ascan_set_attack(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置主动扫描攻击参数。"""
    self.attack_policy["attackEnabled"] = bool(int(b.get("state") or 0))
    return {"attackEnabled": "true" if self.attack_policy["attackEnabled"] else "false"}


def _ascan_set_rule(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置主动扫描规则。"""
    rule_id = str(b.get("ruleId") or "")
    state = bool(int(b.get("state") or 0))
    if state:
        self.ascan_enabled.add(rule_id)
    else:
        self.ascan_enabled.discard(rule_id)
    self.attack_policy["enabledRules"] = ",".join(sorted(self.ascan_enabled))
    return {"ruleId": rule_id, "state": "true" if state else "false"}


def _ascan_scan(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """受控主动扫描：只对 scope 内、未被排除的端点跑已启用规则。"""
    if not self.attack_policy.get("attackEnabled", True):
        return {"scan": "-1"}
    url = b.get("url") or self.world.base_host + "/"
    if not self.is_in_scope(url):
        return {"scan": "-1"}
    self._scan_seq += 1
    scan_id = str(self._scan_seq)
    self.active_scan_running = True
    max_alerts = int(self.scan_policy.get("maxAlertsPerRule") or 10)
    rule_budget: dict[str, int] = {}
    total_targets = 0
    scanned = 0
    base_netloc = urlsplit(url).netloc
    for endpoint in self.world.endpoints:
        target = self.world.base_host + endpoint.path
        if base_netloc and urlsplit(target).netloc != base_netloc:
            continue
        if not self.is_in_scope(target):
            continue
        if self.is_excluded(target):
            continue
        # 主动扫描走 HTTP 请求：只要配了任一 Session 管理方式（headerBased/cookieBased），
        # 登录保护接口就能访问；浏览器登录态只对 Client Spider 的页面渲染有意义。
        if endpoint.login_required and self.session_method in ("none", ""):
            continue
        if not endpoint.active_rule_ids:
            continue
        total_targets += 1
        scanned += 1
        for rule_id in endpoint.active_rule_ids:
            rule = self._rule_map(self.world).get(rule_id)
            if rule is None or str(rule.rule_id) not in self.ascan_enabled:
                continue
            if rule_budget.get(str(rule.rule_id), 0) >= max_alerts:
                continue
            method = endpoint.methods[0] if endpoint.methods else "GET"
            parameter = endpoint.query_params[0] if endpoint.query_params else (
                endpoint.body_params[0] if endpoint.body_params else ""
            )
            self._emit_alert(
                rule,
                target,
                method=method,
                parameter=parameter,
                attack="zap-mock",
            )
            rule_budget[str(rule.rule_id)] = rule_budget.get(str(rule.rule_id), 0) + 1
    self.active_scan_ids.append(scan_id)
    self.active_scan_progress[scan_id] = {
        "Scan ID": scan_id,
        "Number of alerts": str(sum(1 for _ in self._alerts)),
        "Number of hostnames": str(1),
        "Number of hosts": str(1),
        "Number of context hosts": "0",
        "Number of URLs to scan": str(total_targets),
        "Number of processed URLs": str(scanned),
        "Number of requests": str(self._requests_made),
        "Percentage": "100" if not self.world.simulate_hang else "25",
    }
    if not self.world.simulate_hang:
        self.active_scan_running = False
    return {"scan": scan_id}


def _ascan_stop(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """停止主动扫描。"""
    self.active_scan_running = False
    self._cancelled = True
    return {"Scans stopped": "true"}


def _ascan_progress(self: MockZAPTransport, p: dict, _b: dict, _f: dict) -> dict:
    """读取主动扫描的当前进度。"""
    scan_id = str(p.get("scanId") or "1")
    if scan_id not in self.active_scan_progress:
        raise ZAPTransportError("扫描不存在", status_code=404, path="/JSON/ascan/progress")
    return dict(self.active_scan_progress[scan_id])


def _core_alert(self: MockZAPTransport, p: dict, _b: dict, _f: dict) -> list:
    """ZAP 的 /core/alert 默认按 ruleIds 过滤；不传则全部。"""
    rules = [r.strip() for r in str(p.get("rules") or "").split(",") if r.strip()]
    if rules:
        return [a for a in self._alerts if a["id"] in rules]
    return list(self._alerts)


def _core_alert_json(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> list:
    """将安全告警转换为 JSON 数据。"""
    return list(self._alerts)


def _core_count_alerts(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """统计核心模块告警。"""
    return {"Total": str(len(self._alerts))}


def _core_urls(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> list:
    """列出模拟扫描器已经访问的 URL。"""
    return sorted(self._urls)


def _core_history(self: MockZAPTransport, p: dict, _b: dict, _f: dict) -> list:
    """查询模拟扫描器的请求历史。"""
    start = max(0, int(p.get("start") or 0))
    count = int(p.get("count") or len(self._history))
    return self._history[start : start + count]


def _core_is_alert(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """判断模拟扫描结果是否包含安全告警。"""
    rule_id = str(b.get("ruleId") or "")
    return {"alert": "true" if (rule_id in self.pscan_enabled or rule_id in self.ascan_enabled) else "false"}


def _core_set_alert(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置核心模块告警。"""
    rule_id = str(b.get("ruleId") or "")
    state = bool(int(b.get("state") or 0))
    for bucket in (self.pscan_enabled, self.ascan_enabled):
        if state:
            bucket.add(rule_id)
        else:
            bucket.discard(rule_id)
    return {"ruleId": rule_id, "state": "true" if state else "false"}


def _core_reset_all(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """重置核心模块`all`。"""
    self._alerts.clear()
    self._history.clear()
    self._urls.clear()
    self._pages.clear()
    self.browser_pages_visited.clear()
    self._spider_pages.clear()
    self.in_scope.clear()
    self.in_scope_prefix.clear()
    self.in_scope_regex.clear()
    self.out_of_scope.clear()
    self.excluded_regex.clear()
    self._browser_logged_in_override = None
    self.session_method = "none"
    self.session_value = ""
    self.auth_method = "none"
    return {"result": "ok"}


def _authentication_set_method(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置认证方法。"""
    self.auth_method = b.get("value") or "none"
    return {"value": self.auth_method}


def _authentication_set_strategy(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置认证策略。"""
    self.auth_strategy = b.get("value") or "manual"
    return {"value": self.auth_strategy}


def _authentication_set_logged_in(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置认证登录状态。"""
    self.logged_in_indicator = b.get("regex") or ""
    return {"regex": self.logged_in_indicator}


def _authentication_set_logged_out(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置认证登录状态外。"""
    self.logged_out_indicator = b.get("regex") or ""
    return {"regex": self.logged_out_indicator}


def _authentication_set_user_agent(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置认证`user`智能体。"""
    self.user_agent_script = b.get("script") or ""
    return {"script": self.user_agent_script[:80]}


def _authentication_verify(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """验证当前认证是否有效。

    语义：headerBased / cookieBased Session 已配置且给了 token 才算已登录；
    manual 策略且浏览器未建立会话时算未登录；未配置则无法判定。
    """
    method = self.session_method
    if method in ("none", "", None):
        if self.auth_method == "none":
            return {"loggedIn": "false", "verified": "false"}
        return {"loggedIn": "false", "verified": "false"}
    has_value = bool((self.session_value or "").strip())
    logged_in = has_value or self.auth_strategy == "usernamePassword"
    return {"loggedIn": "true" if logged_in else "false", "verified": "true"}


def _session_set_method(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置会话方法。"""
    self.session_method = b.get("value") or "none"
    return {"value": self.session_method}


def _session_set_name(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置会话名称。"""
    self.session_name = b.get("value") or ""
    return {"value": self.session_name}


def _session_set_header(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置会话请求头。"""
    self.session_header = b.get("header") or ""
    return {"header": self.session_header}


def _session_set_value(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置会话值。"""
    self.session_value = b.get("value") or ""
    return {"value": "******" if self.session_value else ""}


def _session_set_token_name(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """设置会话令牌名称。"""
    self.session_token_name = b.get("value") or ""
    return {"value": self.session_token_name}


def _openapi_add(self: MockZAPTransport, _p: dict, _b: dict, files: dict) -> dict:
    """OpenAPI 导入。files 里至少有一个文件项。"""
    if not self.world.has_openapi:
        raise ZAPTransportError("OpenAPI 组件不可用", status_code=404, path="/JSON/openapi/add")
    payload = ""
    for value in files.values():
        if isinstance(value, (bytes, str)):
            payload = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
        elif isinstance(value, tuple):
            # httpx 的文件元组是 (文件名, 内容, 类型) 或 (文件名, 内容)。
            content = value[1] if len(value) > 1 else b""
            payload = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        elif isinstance(value, dict):
            payload = value.get("content") or payload
    self.openapi_imports.append({"size": len(payload)})
    return {"openapi_id": "1", "swagger_2": "0", "openapi_3": "1"}


def _scannerpool_list(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> list:
    """列出`scannerpool`。"""
    if not self.world.has_scannerpool:
        raise ZAPTransportError("scannerpool 组件不可用", status_code=404, path="/JSON/scannerpool/list")
    return [{"name": "default", "id": 1}]


def _ajax_spider(self: MockZAPTransport, _p: dict, b: dict, _f: dict) -> dict:
    """执行模拟 AJAX 爬虫扫描。"""
    if not self.world.has_ajax_spider:
        raise ZAPTransportError("AJAX Spider 组件不可用", status_code=404)
    return _client_spider(self, _p, b, _f)


def _ajax_spider_stop(self: MockZAPTransport, _p: dict, _b: dict, _f: dict) -> dict:
    """停止AJAX爬虫。"""
    if not self.world.has_ajax_spider:
        raise ZAPTransportError("AJAX Spider 组件不可用", status_code=404)
    return _stop_client_spider(self, _p, _b, _f)


#: 端点分发表：(METHOD, PATH) → handler。MockZAPTransport.request 只认这张表，
#: 新增端点必须在这里登记，否则测试会立刻报「Mock ZAP 未实现端点」。
_HANDLERS: dict[tuple[str, str], Any] = {
    ("GET", "/JSON/core/about"): _about,
    ("POST", "/JSON/core/about"): _about,
    ("GET", "/JSON/core/version"): _core_version,
    ("POST", "/JSON/core/version"): _core_version,
    ("POST", "/JSON/core/setTargetInScope"): _set_in_scope,
    ("POST", "/JSON/core/setTargetInScopePrefix"): _set_in_scope_prefix,
    ("POST", "/JSON/core/setTargetInScopeRegex"): _set_in_scope_regex,
    ("POST", "/JSON/core/setTargetOutOfScope"): _set_out_of_scope,
    ("POST", "/JSON/core/setTargetExcludeFromScanRegex"): _set_excluded,
    ("POST", "/JSON/core/setOptionInScopeOnlyScan"): _set_scan_out_of_scope,
    ("POST", "/JSON/core/resetAll"): _core_reset_all,
    ("POST", "/JSON/core/alert"): _core_alert,
    ("POST", "/JSON/core/alertJson"): _core_alert_json,
    ("POST", "/JSON/core/countAlerts"): _core_count_alerts,
    ("GET", "/JSON/core/urls"): _core_urls,
    ("GET", "/JSON/core/history"): _core_history,
    ("POST", "/JSON/core/isAlertOn"): _core_is_alert,
    ("POST", "/JSON/core/setAlertOn"): _core_set_alert,
    ("POST", "/JSON/spider/spider"): _spider,
    ("POST", "/JSON/spider/stopSpider"): _stop_spider,
    ("POST", "/JSON/spider/isRunning"): _spider_is_running,
    ("GET", "/JSON/spider/isRunning"): _spider_is_running,
    ("POST", "/JSON/clientspider/clientspider"): _client_spider,
    ("POST", "/JSON/clientspider/stopClientSpider"): _stop_client_spider,
    ("POST", "/JSON/clientspider/isClientSpiderRunning"): _client_spider_is_running,
    ("POST", "/JSON/clientspider/setMaxCrawlDepth"): _client_spider_set_depth,
    ("POST", "/JSON/clientspider/setPageCount"): _client_spider_set_pages,
    ("POST", "/JSON/clientspider/setTargetRegex"): _client_spider_set_regex,
    ("POST", "/JSON/clientspider/setMaxCrawlState"): _client_spider_set_state,
    ("POST", "/JSON/pscan/getActiveRules"): _pscan_get_rules,
    ("POST", "/JSON/pscan/getPolicy"): _pscan_get_policy,
    ("POST", "/JSON/pscan/getMode"): _pscan_get_mode,
    ("POST", "/JSON/pscan/setMode"): _pscan_set_mode,
    ("POST", "/JSON/pscan/setAlertOn"): _pscan_set_alert,
    ("POST", "/JSON/pscan/isAlertOn"): _pscan_is_alert,
    ("POST", "/JSON/pscan/waitForPscanCompletion"): _pscan_wait,
    ("GET", "/JSON/pscan/progress"): _pscan_progress,
    ("POST", "/JSON/pscan/progress"): _pscan_progress,
    ("POST", "/JSON/ascan/getAttackPolicy"): _ascan_get_policy,
    ("POST", "/JSON/ascan/setAttackPolicy"): _ascan_set_policy,
    ("POST", "/JSON/ascan/getScanPolicy"): _ascan_get_scan_policy,
    ("POST", "/JSON/ascan/setScanPolicy"): _ascan_set_scan_policy,
    ("POST", "/JSON/ascan/setConcurrency"): _ascan_set_concurrency,
    ("POST", "/JSON/ascan/setRequestTimingInMs"): _ascan_set_timing,
    ("POST", "/JSON/ascan/setMaxDurationInMinutes"): _ascan_set_max_duration,
    ("POST", "/JSON/ascan/setMaxRuleDurationInMinutes"): _ascan_set_max_rule_duration,
    ("POST", "/JSON/ascan/setMaxAlertsPerRule"): _ascan_set_max_alerts,
    ("POST", "/JSON/ascan/setDefaultRuleThreshold"): _ascan_set_threshold,
    ("POST", "/JSON/ascan/enableAttack"): _ascan_set_attack,
    ("POST", "/JSON/ascan/enableRule"): _ascan_set_rule,
    ("POST", "/JSON/ascan/scan"): _ascan_scan,
    ("POST", "/JSON/ascan/stopScan"): _ascan_stop,
    ("GET", "/JSON/ascan/progress"): _ascan_progress,
    ("POST", "/JSON/authentication/setAuthenticationMethod"): _authentication_set_method,
    ("POST", "/JSON/authentication/setAuthenticationStrategy"): _authentication_set_strategy,
    ("POST", "/JSON/authentication/setLoggedInIndicator"): _authentication_set_logged_in,
    ("POST", "/JSON/authentication/setLoggedOutIndicator"): _authentication_set_logged_out,
    ("POST", "/JSON/authentication/setUserAgent"): _authentication_set_user_agent,
    ("POST", "/JSON/authentication/verifyAuthentication"): _authentication_verify,
    ("POST", "/JSON/session/setSessionManagementMethod"): _session_set_method,
    ("POST", "/JSON/session/setName"): _session_set_name,
    ("POST", "/JSON/session/setHeader"): _session_set_header,
    ("POST", "/JSON/session/setValue"): _session_set_value,
    ("POST", "/JSON/session/setTokenName"): _session_set_token_name,
    ("POST", "/JSON/openapi/add"): _openapi_add,
    ("GET", "/JSON/scannerpool/list"): _scannerpool_list,
    ("POST", "/JSON/ajaxSpider/ajaxSpider"): _ajax_spider,
    ("POST", "/JSON/ajaxSpider/stopAjaxSpider"): _ajax_spider_stop,
}

#: ZAP 规则 → CWE / WASC 映射（只填常用几条，未登记的落 0）。
_CWE_BY_RULE: dict[int, int] = {
    10010: 1004,
    10012: 1004,
    10015: 1021,
    10020: 200,
    10021: 200,
    10035: 693,
    10036: 693,
    10038: 1004,
    10095: 611,
    30001: 22,
    40004: 79,
    40013: 1004,
    40018: 352,
    40029: 601,
    60001: 89,
    60002: 89,
    60103: 79,
    60106: 79,
    60213: 693,
    90022: 1021,
}

_WASC_BY_RULE: dict[int, int] = {
    10010: 13,
    10012: 13,
    10015: 4,
    10020: 13,
    10021: 13,
    10035: 4,
    10036: 4,
    10038: 13,
    10095: 4,
    30001: 4,
    40004: 15,
    40013: 13,
    40018: 9,
    40029: 9,
    60001: 19,
    60002: 19,
    60103: 15,
    60106: 15,
    60213: 4,
    90022: 4,
}
