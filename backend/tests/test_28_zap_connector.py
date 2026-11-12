"""ZAP Connector 单元测试（Phase A）。

全部跑在 Mock ZAP 上，不发任何出站请求、不连数据库。
真实 ZAP 集成测试见 docs/zap/（需要 Docker，本环境不可用）。

覆盖范围（对应交付要求 §三十六「ZAP Connector 与扫描引擎」部分）：
- 传输层：base_url 约束、API Key 传递方式、超时与连接失败、非 JSON 响应
- Connector：健康检查、版本下限、API Key 拒绝、连接不可达、缺少插件、能力探测降级
- 范围：in-scope / exclude-from-scan 正则转义、上下文创建与清理
- 认证：Bearer / Header / CookieBased / 未配置；**配了 Header 不等于页面已登录**
- 爬虫：传统 Spider vs Client Spider 的可达性差异；被动扫描等待与超时
- 主动扫描：限额硬截断、规则选择、排除路径、攻击关闭、组件缺失
- 结果：字段映射、Severity 映射、Confidence 保留、凭据脱敏、清理后不复用
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.features.security_testing.zap.contracts import (
    AUTH_MODE_BEARER_TOKEN,
    AUTH_MODE_BROWSER_AUTH,
    AUTH_MODE_MANUAL,
    AUTH_MODE_NONE,
    AUTH_STATUS_LOGGED_IN,
    AUTH_STATUS_LOGGED_OUT,
    AUTH_STATUS_UNVERIFIABLE,
    REDACTED_PLACEHOLDER,
    map_zap_risk,
    redact_text,
    redact_url,
)
from app.features.security_testing.zap.connector import (
    ACTIVE_MAX_ALERTS_PER_RULE_HARD_CAP,
    ACTIVE_MAX_CONCURRENCY_HARD_CAP,
    ACTIVE_MAX_DURATION_HARD_CAP,
    ACTIVE_MAX_RULE_DURATION_HARD_CAP,
    ZAPConnector,
    ZAPConnectorError,
    ZAP_REASON_ACTIVE_FAILED,
    ZAP_REASON_API_AUTH_FAILED,
    ZAP_REASON_CONTEXT_FAILED,
    ZAP_REASON_PLUGIN_MISSING,
    ZAP_REASON_SCOPE_VIOLATION,
    ZAP_REASON_UNAVAILABLE,
    ZAP_REASON_VERSION_UNSUPPORTED,
    is_supported_version,
    parse_zap_version,
)
from app.features.security_testing.zap.mock import (
    _HANDLERS,
    MOCK_TOKEN_VALUE,
    MockEndpoint,
    MockRule,
    MockZAPTransport,
    MockZAPWorld,
)
from app.features.security_testing.zap.transport import (
    HttpZAPTransport,
    ZAP_API_KEY_HEADER,
    ZAP_DISABLE_CSRF_HEADER,
    ZAP_FORMAT_PARAM,
    ZAPTransportError,
)

BASE_URL = "https://test.example.com"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1MSJ9.signature"


def make_mock(world: MockZAPWorld | None = None, **kwargs) -> MockZAPTransport:
    """构造一个带默认端的 Mock 传输层。"""
    return MockZAPTransport(world or MockZAPWorld(base_host=BASE_URL), **kwargs)


def make_connector(world: MockZAPWorld | None = None, **kwargs) -> ZAPConnector:
    """构造一个跑在 Mock ZAP 上的连接器；传 world 时可以定制插件与端点。"""
    return ZAPConnector(make_mock(world, **kwargs), **{"timeout_seconds": 5.0})


def apply_default_scope(connector: ZAPConnector) -> None:
    """应用默认范围。"""
    connector.apply_scope(base_url=BASE_URL, allowed_hosts=["test.example.com"])


def bear_auth() -> dict:
    """一个 API 侧的 Bearer Token 配置（注意：这只覆盖 API 请求，不覆盖浏览器页面）。"""
    return {
        "auth_mode": AUTH_MODE_BEARER_TOKEN,
        "session_method": "headerBased",
        "session_header": "Authorization",
        "session_name": "Authorization",
        "session_value": f"Bearer {JWT}",
        "logged_in_indicator": '"id"',
        "logged_out_indicator": "/login",
    }


# --------------------------------------------------------------------------- 传输层


class _FakeResponse:
    """最小 httpx.Response 替身。"""

    def __init__(self, status_code: int = 200, body=None, text: str = "") -> None:
        """初始化对象状态。"""
        self.status_code = status_code
        self._body = body
        self.text = text or (json.dumps(body, ensure_ascii=False) if body is not None else "")

    def json(self):
        """返回模拟 HTTP 响应的 JSON 数据。"""
        if self._body is None:
            raise ValueError("响应体不是 JSON")
        return self._body


class _FakeClient:
    """记录调用参数的 httpx.Client 替身。"""

    def __init__(self, response=_FakeResponse(), raises: Exception | None = None) -> None:
        """初始化对象状态。"""
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []
        self.closed = False

    def request(self, method, path, params=None, json=None, files=None, timeout=None):
        """记录并返回一次模拟 ZAP 客户端请求。"""
        self.calls.append({"method": method, "path": path, "params": params,
                           "json": json, "files": files, "timeout": timeout})
        if self.raises is not None:
            raise self.raises
        return self.response

    def close(self) -> None:
        """关闭对应数据。"""
        self.closed = True


def build_transport(
    monkeypatch,
    *,
    fake_client: _FakeClient | None = None,
    raises: Exception | None = None,
    base_url="http://10.0.0.10:8090",
    api_key="***",
    api_key_mode="header",
) -> tuple[HttpZAPTransport, _FakeClient]:
    """构造一个带假 httpx.Client 的 HttpZAPTransport。

    fake_client 每次调用都新建——早先的写法用函数默认值当共享对象，
    所有用例共用同一个 response 与 calls 列表，断言会互相污染。
    client_kwargs 挂回 client 上，便于断言构造时的 headers / trust_env。
    """
    client = fake_client if fake_client is not None else _FakeClient(
        response=_FakeResponse(200, {"version": "2.16.0"}), raises=raises,
    )
    captured: dict[str, Any] = {}

    def fake_client_cls(**kwargs):
        """构造可捕获请求参数的模拟 ZAP 客户端类。"""
        captured.update(kwargs)
        return client

    monkeypatch.setattr(httpx, "Client", fake_client_cls)
    transport = HttpZAPTransport(
        base_url, api_key=api_key, api_key_mode=api_key_mode, timeout_seconds=7.0,
    )
    captured["client_kwargs"] = captured
    client.client_kwargs = captured  # type: ignore[attr-defined]
    return transport, client


class TestTransport:
    def test_requires_base_url(self):
        """验证需要`base`URL场景及其预期结果。"""
        with pytest.raises(ValueError, match="base_url 不能为空"):
            HttpZAPTransport("")

    def test_base_host_only_exposes_netloc(self, monkeypatch):
        """验证`base``host`仅`exposes``netloc`场景及其预期结果。"""
        transport, _ = build_transport(monkeypatch, base_url="http://10.0.0.10:8090/proxy/api/")
        assert transport.base_host == "http://10.0.0.10:8090"

    def test_api_key_sent_as_header_by_default(self, monkeypatch):
        """验证API键`sent``as`请求头按默认场景及其预期结果。"""
        transport, fake = build_transport(monkeypatch)
        transport.request(method="GET", path="/JSON/core/about")
        assert fake.client_kwargs["headers"][ZAP_API_KEY_HEADER] == "***"
        # 头模式不把 key 放进查询串。
        assert "apikey" not in fake.calls[0]["params"]
        assert fake.calls[0]["params"][ZAP_FORMAT_PARAM] == "json"
        # CSRF 头必须关，否则脚本调用会被 ZAP 拦下。
        assert fake.client_kwargs["headers"][ZAP_DISABLE_CSRF_HEADER] == "true"

    def test_api_key_query_mode_puts_key_in_query(self, monkeypatch):
        """验证API键查询参数`mode``puts`键`in`查询参数场景及其预期结果。"""
        transport, fake = build_transport(monkeypatch, api_key_mode="query")
        transport.request(method="GET", path="/JSON/core/about")
        assert "apikey" in fake.calls[0]["params"]
        assert ZAP_API_KEY_HEADER not in fake.client_kwargs["headers"]

    def test_absolute_url_path_is_rejected(self, monkeypatch):
        """绝对 URL 会被 httpx 当独立地址，绕过 base_url 约束。"""
        transport, fake = build_transport(monkeypatch)
        with pytest.raises(ZAPTransportError, match="协议头"):
            transport.request(method="GET", path="http://evil.example/api")
        assert fake.calls == []

    def test_timeout_maps_to_transport_error(self, monkeypatch):
        """验证`timeout``maps`到`transport`错误场景及其预期结果。"""
        transport, _ = build_transport(
            monkeypatch,
            raises=httpx.TimeoutException("超时", request=httpx.Request("GET", "http://x/api")),
        )
        with pytest.raises(ZAPTransportError) as excinfo:
            transport.request(method="GET", path="/JSON/core/about")
        assert "超时" in excinfo.value.message

    def test_http_error_maps_to_transport_error(self, monkeypatch):
        """验证HTTP错误`maps`到`transport`错误场景及其预期结果。"""
        transport, _ = build_transport(monkeypatch, raises=httpx.ConnectError("连接失败"))
        with pytest.raises(ZAPTransportError) as excinfo:
            transport.request(method="GET", path="/JSON/core/about")
        assert "连接失败" in excinfo.value.message

    def test_non_json_response_raises(self, monkeypatch):
        """验证`non`JSON响应`raises`场景及其预期结果。"""
        transport, _ = build_transport(
            monkeypatch, fake_client=_FakeClient(response=_FakeResponse(200, None, "<html>login</html>")),
        )
        with pytest.raises(ZAPTransportError, match="非 JSON"):
            transport.request(method="GET", path="/JSON/core/about")

    def test_error_body_is_truncated(self, monkeypatch):
        """验证错误请求体是否`truncated`场景及其预期结果。"""
        transport, _ = build_transport(
            monkeypatch, fake_client=_FakeClient(response=_FakeResponse(500, {"detail": "x" * 4000})),
        )
        with pytest.raises(ZAPTransportError) as excinfo:
            transport.request(method="GET", path="/JSON/core/about")
        assert excinfo.value.status_code == 500
        assert len(str(excinfo.value.response_body)) <= 505

    def test_close_is_idempotent(self, monkeypatch):
        """验证关闭是否幂等场景及其预期结果。"""
        transport, fake = build_transport(monkeypatch)
        transport.close()
        transport.close()
        assert fake.closed is True


class TestConnectorBasics:
    def test_health_returns_version_and_addons(self):
        """验证`health``returns`版本和`addons`场景及其预期结果。"""
        about = make_connector().check_health()
        assert about.version == "2.16.0"
        assert "clientSpider" in about.add_on_names
        assert about.add_on_versions["clientSpider"] == "2.4.0"

    def test_version_below_minimum_is_rejected(self):
        """验证版本`below``minimum`是否被拒绝场景及其预期结果。"""
        connector = ZAPConnector(make_mock(MockZAPWorld(base_host=BASE_URL, version="2.11.0")))
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.check_health()
        assert excinfo.value.reason == ZAP_REASON_VERSION_UNSUPPORTED
        assert excinfo.value.retryable is False

    def test_version_at_minimum_is_accepted(self):
        """验证版本`at``minimum`是否`accepted`场景及其预期结果。"""
        connector = ZAPConnector(make_mock(MockZAPWorld(base_host=BASE_URL, version="2.12.0")))
        assert connector.check_health().version == "2.12.0"

    def test_unparseable_version_is_rejected(self):
        """验证`unparseable`版本是否被拒绝场景及其预期结果。"""
        connector = ZAPConnector(make_mock(MockZAPWorld(base_host=BASE_URL, version="unknown")))
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.check_health()
        assert excinfo.value.reason == ZAP_REASON_VERSION_UNSUPPORTED

    def test_connectivity_failure_is_retryable_unavailable(self, monkeypatch):
        """连不上（无 HTTP 状态码）必须映射成不可用且标记可重试。"""
        connector = make_connector()

        def boom(**kwargs):
            """模拟 ZAP 传输层抛出异常。"""
            raise ZAPTransportError("ZAP 连接失败", path="/JSON/core/about")

        monkeypatch.setattr(connector._state.transport, "request", boom)
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.check_health()
        assert excinfo.value.reason == ZAP_REASON_UNAVAILABLE
        assert excinfo.value.retryable is True
        assert excinfo.value.status_code is None

    def test_unknown_exception_is_wrapped_not_propagated(self, monkeypatch):
        """传输层实现抛出的意外异常要收敛成 Connector 错误，不能打挂 Worker。"""
        connector = make_connector()

        def boom(**kwargs):
            """模拟 ZAP 传输层抛出异常。"""
            raise RuntimeError("底层崩溃")

        monkeypatch.setattr(connector._state.transport, "request", boom)
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.check_health()
        assert "RuntimeError" in excinfo.value.message
        assert excinfo.value.reason == "ZAP_BAD_RESPONSE"

    def test_api_key_rejected_maps_to_auth_failed(self, monkeypatch):
        """验证API键被拒绝`maps`到认证失败场景及其预期结果。"""
        transport, _ = build_transport(monkeypatch, api_key="***")
        transport._client = _FakeClient(response=_FakeResponse(401, {"detail": "key rejected"}))
        connector = ZAPConnector(transport)
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.check_health()
        assert excinfo.value.reason == ZAP_REASON_API_AUTH_FAILED
        assert excinfo.value.retryable is False
        # 错误信息不能带出响应体里的内部细节之外的凭据。
        assert "test-zap-key-001" not in excinfo.value.message

    def test_server_5xx_is_retryable(self, monkeypatch):
        """验证服务端`xx`是否`retryable`场景及其预期结果。"""
        transport, _ = build_transport(monkeypatch)
        transport._client = _FakeClient(response=_FakeResponse(503, {"detail": "busy"}))
        connector = ZAPConnector(transport)
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.check_health()
        assert excinfo.value.retryable is True

    def test_capabilities_reports_unsupported_components(self):
        """验证`capabilities``reports``unsupported``components`场景及其预期结果。"""
        caps = make_connector().get_capabilities()
        assert caps.version == "2.16.0"
        names = {cap.name: cap for cap in caps.capabilities}
        assert names["clientspider"].supported is True
        assert names["active.limits"].supported is True
        # scannerpool 在默认 Mock 世界里不存在，必须如实报不支持。
        assert names["scannerpool"].supported is False
        assert "不存在" in names["scannerpool"].detail

    def test_capabilities_without_scannerpool_addon(self):
        """验证`capabilities`不带`scannerpool``addon`场景及其预期结果。"""
        world = MockZAPWorld(base_host=BASE_URL, has_scannerpool=True)
        caps = ZAPConnector(make_mock(world)).get_capabilities()
        names = {cap.name: cap for cap in caps.capabilities}
        assert names["scannerpool"].supported is True

    def test_capabilities_degrades_when_unreachable(self, monkeypatch):
        """验证`capabilities``degrades`当`unreachable`场景及其预期结果。"""
        transport, _ = build_transport(monkeypatch)
        transport._client = _FakeClient(
            response=_FakeResponse(401, {"detail": "key rejected"}),
        )
        connector = ZAPConnector(transport)
        # 能力探测不能因为服务不可用就整页抛错。
        caps = connector.get_capabilities()
        assert caps.version == "unknown"
        assert caps.capabilities[0].name == "core.about"
        assert caps.capabilities[0].supported is False

    def test_capability_probe_never_mutates_state(self):
        """能力探测必须全部只读——探测本身不该启动一次爬取。"""
        connector = make_connector()
        transport = connector._state.transport
        connector.get_capabilities()
        assert transport._alerts == []
        assert transport._requests_made == 0
        assert transport.spider_running is False
        assert transport.client_spider_running is False
        assert transport.active_scan_ids == []

    def test_get_version_does_not_gate_on_minimum(self):
        """验证获取版本是否不`gate``on``minimum`场景及其预期结果。"""
        connector = ZAPConnector(make_mock(MockZAPWorld(base_host=BASE_URL, version="2.11.0")))
        # get_version 只取版本，供能力页展示真实版本用，不做下限拦截。
        assert connector.get_version() == "2.11.0"


# --------------------------------------------------------------------------- 范围与上下文


class TestScopeAndContext:
    def test_apply_scope_sets_host_and_regex(self):
        """验证应用范围`sets``host`和`regex`场景及其预期结果。"""
        connector = make_connector()
        connector.apply_scope(
            base_url=BASE_URL,
            allowed_hosts=["test.example.com"],
            include_paths=["/users"],
            exclude_paths=["/logout", "/delete"],
        )
        transport = connector._state.transport
        assert transport.in_scope == ["test.example.com"]
        assert any("/users" in r for r in transport.in_scope_regex)
        assert len(transport.excluded_regex) == 2

    def test_apply_scope_defaults_to_base_host(self):
        """验证应用范围`defaults`到`base``host`场景及其预期结果。"""
        connector = make_connector()
        connector.apply_scope(base_url=BASE_URL)
        assert connector._state.transport.in_scope == ["test.example.com"]

    def test_apply_scope_escapes_regex_metacharacters(self):
        """验证应用范围`escapes``regex``metacharacters`场景及其预期结果。"""
        connector = make_connector()
        connector.apply_scope(base_url=BASE_URL, exclude_paths=["/a.b(c)", "/x*"])
        joined = "|".join(connector._state.transport.excluded_regex)
        # 点号、括号、星号都必须被转义，否则用户输入会被当成正则执行。
        assert r"\." in joined
        assert r"\(" in joined
        assert r"\*" in joined

    def test_create_scan_context_rejects_empty_host(self):
        """验证创建扫描上下文拒绝空值`host`场景及其预期结果。"""
        with pytest.raises(ZAPConnectorError) as excinfo:
            make_connector().create_scan_context(host_pattern="   ")
        assert excinfo.value.reason == ZAP_REASON_CONTEXT_FAILED

    def test_create_scan_context_prefix_mode(self):
        """验证创建扫描上下文`prefix``mode`场景及其预期结果。"""
        connector = make_connector()
        connector.create_scan_context(host_pattern=".example.com")
        assert connector._state.transport.in_scope_prefix == [".example.com"]
        assert connector._state.transport.in_scope == []

    def test_create_scan_context_exact_mode(self):
        """验证创建扫描上下文`exact``mode`场景及其预期结果。"""
        connector = make_connector()
        connector.create_scan_context(host_pattern="test.example.com")
        assert connector._state.transport.in_scope == ["test.example.com"]

    def test_scope_blocks_out_of_scope_requests(self):
        """范围校验在出站前完成：请求不会到达 ZAP，也不会留下任何扫描产物。"""
        connector = make_connector()
        connector.apply_scope(base_url=BASE_URL, allowed_hosts=["test.example.com"])
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.start_spider("https://other.example/")
        assert excinfo.value.reason == ZAP_REASON_SCOPE_VIOLATION
        # 没有发出任何扫描请求，因此也不会有发现与告警。
        assert connector._state.transport.spider_running is False
        assert connector._state.transport._spider_pages == []
        assert connector.list_urls() == []
        assert connector.get_alerts() == []

    def test_out_of_scope_active_scan_is_rejected(self):
        """主动扫描同样受范围约束，不能靠换入口绕过。"""
        connector = make_connector()
        connector.apply_scope(base_url=BASE_URL, allowed_hosts=["test.example.com"])
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.start_active_scan("https://other.example/")
        assert excinfo.value.reason == ZAP_REASON_SCOPE_VIOLATION

    def test_excluded_paths_are_not_scanned(self):
        """验证`excluded``paths`是否为不`scanned`场景及其预期结果。"""
        connector = make_connector()
        connector.apply_scope(base_url=BASE_URL, allowed_hosts=["test.example.com"])
        world = connector._state.transport.world
        world.endpoints.append(MockEndpoint("/payment", active_rule_ids=[30001]))
        scan_id = connector.start_active_scan(BASE_URL, excluded_paths=["/payment"])
        assert scan_id == "1"
        # 被排除的路径不应该出现在告警里。
        assert not any("/payment" in a.url for a in connector.get_alerts())

    def test_clean_scan_context_resets_everything(self):
        """验证`clean`扫描上下文`resets``everything`场景及其预期结果。"""
        connector = make_connector()
        connector.apply_scope(base_url=BASE_URL)
        connector.configure_authentication(bear_auth())
        connector.start_spider(BASE_URL)
        assert connector.get_alerts()
        connector.clean_scan_context()
        transport = connector._state.transport
        assert connector.get_alerts() == []
        assert connector.list_urls() == []
        assert transport.in_scope == []
        assert transport.session_method == "none"
        assert transport.browser_pages_visited == []


# --------------------------------------------------------------------------- 认证


class TestAuthentication:
    def test_bearer_token_verified_logged_in(self):
        """验证`bearer`令牌`verified``logged``in`场景及其预期结果。"""
        result = make_connector().configure_authentication(bear_auth())
        assert result.authenticated is True
        assert result.verified is True
        assert result.status == AUTH_STATUS_LOGGED_IN
        assert result.auth_mode == AUTH_MODE_BEARER_TOKEN

    def test_bearer_without_value_is_logged_out(self):
        """验证`bearer`不带值是否`logged``out`场景及其预期结果。"""
        auth = bear_auth()
        auth["session_value"] = ""
        result = make_connector().configure_authentication(auth)
        assert result.status == AUTH_STATUS_LOGGED_OUT
        assert result.authenticated is False
        assert result.verified is True

    def test_none_mode_is_unverifiable(self):
        """验证`none``mode`是否`unverifiable`场景及其预期结果。"""
        result = make_connector().configure_authentication({"auth_mode": AUTH_MODE_NONE})
        assert result.status == AUTH_STATUS_UNVERIFIABLE
        assert result.verified is False

    def test_verify_authentication_without_plugin_is_unverifiable(self):
        """认证端点缺失时必须是「无法判定」，不能当成「已验证未登录」。"""
        connector = make_connector()
        handler = _HANDLERS.pop(("POST", "/JSON/authentication/verifyAuthentication"))
        try:
            authenticated, verified = connector.verify_authentication()
        finally:
            _HANDLERS[("POST", "/JSON/authentication/verifyAuthentication")] = handler
        assert (authenticated, verified) == (False, False)

    def test_credential_never_leaks_into_result(self):
        """认证结果里不允许出现任何凭据明文。"""
        result = make_connector().configure_authentication(bear_auth())
        rendered = f"{result!r}|{result.detail}|{result.status}"
        assert JWT not in rendered
        assert "Bearer" not in result.detail

    def test_credential_stored_only_in_transport_not_in_connector(self):
        """验证`credential``stored`仅`in``transport`不`in``connector`场景及其预期结果。"""
        connector = make_connector()
        connector.configure_authentication(bear_auth())
        # 连接器只记能力位，不保留值。
        assert connector._state.has_session_value is True
        assert JWT not in repr(connector)
        assert JWT not in str(connector._state.auth_mode)

    def test_browser_session_established_true_for_cookie_based(self):
        """验证浏览器会话`established``true`用于`cookie``based`场景及其预期结果。"""
        connector = make_connector()
        connector.configure_authentication({
            "auth_mode": AUTH_MODE_BROWSER_AUTH,
            "session_method": "cookieBased",
            "session_header": "Cookie",
            "session_name": "session",
            "session_value": "session=abc",
        })
        ok, reason = connector.browser_session_established()
        assert ok is True
        assert "cookieBased" in reason

    def test_browser_session_not_established_with_header_based(self):
        """§十二 核心断言：配了 Authorization Header 不等于 React 页面已登录。"""
        connector = make_connector()
        connector.configure_authentication(bear_auth())
        ok, reason = connector.browser_session_established()
        assert ok is False
        assert "SPA" in reason or "登录页" in reason

    def test_browser_session_manual_mode_reports_unsupported(self):
        """§十三 核心断言：无法提供人工浏览器交互时必须如实显示不支持。"""
        connector = make_connector()
        connector.configure_authentication({
            "auth_mode": AUTH_MODE_MANUAL,
            "session_method": "none",
        })
        ok, reason = connector.browser_session_established()
        assert ok is False
        assert "未提供该能力" in reason

    def test_browser_session_false_for_none(self):
        """验证浏览器会话`false`用于`none`场景及其预期结果。"""
        connector = make_connector()
        ok, reason = connector.browser_session_established()
        assert ok is False

    def test_browser_session_false_when_cookie_value_missing(self):
        """验证浏览器会话`false`当`cookie`值缺失场景及其预期结果。"""
        connector = make_connector()
        connector.configure_authentication({
            "auth_mode": AUTH_MODE_BROWSER_AUTH,
            "session_method": "cookieBased",
            "session_header": "Cookie",
            "session_name": "session",
            "session_value": "   ",
        })
        ok, reason = connector.browser_session_established()
        assert ok is False
        assert "未提供会话值" in reason

    def test_browser_session_reset_after_cleanup(self):
        """验证浏览器会话重置之后清理场景及其预期结果。"""
        connector = make_connector()
        connector.configure_authentication(bear_auth())
        connector.clean_scan_context()
        ok, _ = connector.browser_session_established()
        assert ok is False
        assert connector._state.has_session_value is False


# --------------------------------------------------------------------------- 爬虫与被动扫描


class TestSpidersAndPassive:
    def test_traditional_spider_skips_spa_and_login_pages(self):
        """验证`traditional`爬虫`skips``spa`和登录`pages`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.start_spider(BASE_URL)
        connector.wait_passive_scan(5)
        pages = connector._state.transport._spider_pages
        assert pages
        assert not any("/app/" in p for p in pages)
        assert not any("/api/v1/" in p for p in pages)

    def test_client_spider_discovers_spa_pages_with_browser_session(self):
        """验证客户端爬虫`discovers``spa``pages`包含浏览器会话场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.configure_authentication({
            "auth_mode": AUTH_MODE_BROWSER_AUTH,
            "session_method": "cookieBased",
            "session_header": "Cookie",
            "session_name": "session",
            "session_value": "session=abc",
        })
        connector.start_client_spider(BASE_URL, max_depth=6)
        connector.wait_passive_scan(5)
        visited = connector._state.transport.browser_pages_visited
        assert any("/app/dashboard" in p for p in visited)
        # XHR/Fetch 采集：页面内发起的请求也会被访问到。
        assert any("/api/v1/dashboard" in p for p in visited)

    def test_client_spider_with_only_bearer_reaches_nothing(self):
        """§十二 端到端断言：只配 Bearer Token 时，SPA 路由一个都到不了。"""
        connector = make_connector()
        apply_default_scope(connector)
        result = connector.configure_authentication(bear_auth())
        assert result.status == AUTH_STATUS_LOGGED_IN  # API 侧认证是成功的
        connector.start_client_spider(BASE_URL, max_depth=6)
        connector.wait_passive_scan(5)
        assert connector._state.transport.browser_pages_visited == []
        assert connector.list_urls() == []

    def test_client_spider_with_manual_login_reaches_business_pages(self):
        """§十三：人工扫码后浏览器有会话，业务页面才可达。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector._state.transport.set_browser_login(True)
        connector.start_client_spider(BASE_URL, max_depth=6)
        connector.wait_passive_scan(5)
        visited = connector._state.transport.browser_pages_visited
        assert any("/app/orders" in p for p in visited)

    def test_client_spider_depth_limit(self):
        """深度 1 时不展开 XHR：XHR 目标没有页面入口，只有深度足够才被采集。"""
        cookie_auth = {
            "auth_mode": AUTH_MODE_BROWSER_AUTH, "session_method": "cookieBased",
            "session_header": "Cookie", "session_name": "session", "session_value": "s=1",
        }
        world = MockZAPWorld(base_host=BASE_URL, endpoints=[
            MockEndpoint("/app/home", spa_only=True, login_required=True,
                         xhr_targets=["/api/hidden"]),
        ])
        shallow = make_connector(world)
        shallow.apply_scope(base_url=BASE_URL)
        shallow.configure_authentication(cookie_auth)
        shallow.start_client_spider(BASE_URL, max_depth=1)
        assert shallow._state.transport.browser_pages_visited == [BASE_URL + "/app/home"]
        deep = make_connector(world)
        deep.apply_scope(base_url=BASE_URL)
        deep.configure_authentication(cookie_auth)
        deep.start_client_spider(BASE_URL, max_depth=6)
        assert any("/api/hidden" in p for p in deep._state.transport.browser_pages_visited)

    def test_client_spider_page_count_limit(self):
        """验证客户端爬虫页面统计上限场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.configure_authentication({
            "auth_mode": AUTH_MODE_BROWSER_AUTH, "session_method": "cookieBased",
            "session_header": "Cookie", "session_name": "session", "session_value": "s=1",
        })
        connector.start_client_spider(BASE_URL, max_depth=6, page_count=2)
        assert len(connector._state.transport.browser_pages_visited) == 2

    def test_client_spider_target_regex_filters(self):
        """验证客户端爬虫目标`regex``filters`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.configure_authentication({
            "auth_mode": AUTH_MODE_BROWSER_AUTH, "session_method": "cookieBased",
            "session_header": "Cookie", "session_name": "session", "session_value": "s=1",
        })
        connector.start_client_spider(BASE_URL, max_depth=6, target_regex=r"/app/dashboard")
        visited = connector._state.transport.browser_pages_visited
        assert visited and all("/app/dashboard" in p for p in visited)

    def test_client_spider_missing_component_raises_plugin_missing(self):
        """验证客户端爬虫缺失`component``raises``plugin`缺失场景及其预期结果。"""
        connector = make_connector(MockZAPWorld(base_host=BASE_URL, has_client_spider=False))
        apply_default_scope(connector)
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.start_client_spider(BASE_URL)
        assert excinfo.value.reason == ZAP_REASON_PLUGIN_MISSING
        assert "Client Spider" in excinfo.value.message

    def test_wait_passive_scan_completes(self):
        """验证`wait``passive`扫描`completes`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.start_spider(BASE_URL)
        progress = connector.wait_passive_scan(timeout_seconds=5, poll_interval=0.05)
        assert progress.running is False

    def test_wait_passive_scan_timeout_keeps_running_true(self):
        """挂起场景：等待超时要返回 running=True，而不是谎报完成。"""
        connector = make_connector(MockZAPWorld(base_host=BASE_URL, simulate_hang=True))
        apply_default_scope(connector)
        connector.start_spider(BASE_URL)
        progress = connector.wait_passive_scan(timeout_seconds=0, poll_interval=0.05)
        assert progress.running is True

    def test_hung_spider_is_stoppable(self):
        """验证`hung`爬虫是否`stoppable`场景及其预期结果。"""
        connector = make_connector(MockZAPWorld(base_host=BASE_URL, simulate_hang=True))
        apply_default_scope(connector)
        connector.start_spider(BASE_URL)
        assert connector._state.transport.spider_running is True
        connector.stop_scan([])
        assert connector._state.transport.spider_running is False

    def test_spider_rejects_url_outside_scope(self):
        """验证爬虫拒绝URL`outside`范围场景及其预期结果。"""
        connector = make_connector()
        connector.apply_scope(base_url=BASE_URL, allowed_hosts=["test.example.com"])
        with pytest.raises(ZAPConnectorError):
            connector.start_spider("https://out.of.scope/")

    def test_progress_reports_stage_and_counts(self):
        """验证`progress``reports``stage`和`counts`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.start_spider(BASE_URL)
        connector.wait_passive_scan(5)
        progress = connector.get_scan_progress([])
        assert progress.running is False
        assert progress.alerts > 0
        assert progress.pages > 0
        # 爬取阶段不给百分比——不能虚构精确进度。
        assert progress.percentage is None


# --------------------------------------------------------------------------- 主动扫描


class TestActiveScan:
    def test_limits_are_hard_capped(self):
        """验证`limits`是否为`hard``capped`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.configure_authentication(bear_auth())
        connector.start_active_scan(
            BASE_URL,
            max_duration=9999,
            max_rule_duration=9999,
            max_concurrency=999,
            request_delay_ms=999999,
            max_alerts_per_rule=99999,
        )
        policy = connector._state.transport.attack_policy
        assert policy["maxDurationInMinutes"] == ACTIVE_MAX_DURATION_HARD_CAP
        assert policy["maxRuleDurationInMinutes"] == ACTIVE_MAX_RULE_DURATION_HARD_CAP
        assert policy["concurrency"] == str(ACTIVE_MAX_CONCURRENCY_HARD_CAP)
        assert policy["requestTimingInMs"] == 2000
        assert connector._state.transport.scan_policy["maxAlertsPerRule"] == ACTIVE_MAX_ALERTS_PER_RULE_HARD_CAP

    def test_only_selected_rules_are_enabled(self):
        """验证仅`selected``rules`是否为启用状态场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.configure_authentication(bear_auth())
        connector.start_active_scan(BASE_URL, selected_rule_ids=["30001", "60001"])
        assert connector._state.transport.ascan_enabled == {"30001", "60001"}

    def test_all_default_rules_enabled_when_no_selection(self):
        """验证`all`默认`rules`启用状态当无`selection`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.configure_authentication(bear_auth())
        connector.start_active_scan(BASE_URL)
        assert len(connector._state.transport.ascan_enabled) > 1
        assert "30001" in connector._state.transport.ascan_enabled

    def test_excluded_paths_are_not_active_scanned(self):
        """验证`excluded``paths`是否为不启用状态`scanned`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.configure_authentication(bear_auth())
        world = connector._state.transport.world
        world.endpoints.append(MockEndpoint("/payment/transfer", active_rule_ids=[60001]))
        connector.start_active_scan(BASE_URL, selected_rule_ids=["60001"], excluded_paths=["/payment"])
        assert not any("/payment" in a.url for a in connector.get_alerts())

    def test_active_scan_requires_login_session_for_protected_endpoints(self):
        """验证启用状态扫描需要登录会话用于`protected``endpoints`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        # 未配置认证：登录保护接口不参与主动扫描。
        connector.start_active_scan(BASE_URL, selected_rule_ids=["60001"])
        assert not any("/api/v1/dashboard" in a.url for a in connector.get_alerts())

    def test_active_scan_rejected_when_attack_disabled(self):
        """验证启用状态扫描被拒绝当`attack``disabled`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector._state.transport.attack_policy["attackEnabled"] = False
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.start_active_scan(BASE_URL)
        assert excinfo.value.reason == ZAP_REASON_ACTIVE_FAILED

    def test_active_scan_rejected_when_out_of_scope(self):
        """验证启用状态扫描被拒绝当`out``of`范围场景及其预期结果。"""
        connector = make_connector()
        connector.apply_scope(base_url=BASE_URL, allowed_hosts=["test.example.com"])
        with pytest.raises(ZAPConnectorError):
            connector.start_active_scan("https://other.example/")

    def test_active_scan_zero_duration_is_clamped(self):
        """验证启用状态扫描`zero``duration`是否`clamped`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.start_active_scan(BASE_URL, max_duration=0, max_concurrency=0)
        assert connector._state.transport.attack_policy["maxDurationInMinutes"] >= 1
        assert connector._state.transport.attack_policy["concurrency"] == "1"

    def test_set_active_scan_limits_also_clamps(self):
        """验证设置启用状态扫描`limits``also``clamps`场景及其预期结果。"""
        connector = make_connector()
        connector.set_active_scan_limits(max_duration=9999, max_rule_duration=0,
                                         max_concurrency=9999, request_delay_ms=-5)
        policy = connector._state.transport.attack_policy
        assert policy["maxDurationInMinutes"] == ACTIVE_MAX_DURATION_HARD_CAP
        assert policy["maxRuleDurationInMinutes"] >= 1
        assert policy["concurrency"] == str(ACTIVE_MAX_CONCURRENCY_HARD_CAP)
        assert policy["requestTimingInMs"] == 0

    def test_stop_scan_stops_active_scan(self):
        """验证停止扫描`stops`启用状态扫描场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.configure_authentication(bear_auth())
        scan_id = connector.start_active_scan(BASE_URL, selected_rule_ids=["30001"])
        connector.stop_scan([scan_id])
        assert connector._state.scan_ids == []

    def test_progress_is_not_running_when_scan_finished(self):
        """验证`progress`是否不`running`当扫描`finished`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.configure_authentication(bear_auth())
        scan_id = connector.start_active_scan(BASE_URL, selected_rule_ids=["30001"])
        progress = connector.get_scan_progress([scan_id])
        assert progress.running is False
        assert progress.percentage == 100


# --------------------------------------------------------------------------- 结果与统计


class TestAlertsAndStatistics:
    def test_alert_fields_are_mapped(self):
        """验证告警`fields`是否为`mapped`场景及其预期结果。"""
        connector = make_connector()
        connector._state.transport.seed_raw_alert({
            "id": "30001",
            "alert": "Path Traversal",
            "risk": "High",
            "confidence": "4",
            "url": "https://test.example.com/reports?q=1",
            "method": "get",
            "param": "q",
            "solution": "使用白名单校验输入",
            "reference": "https://cwe.mitre.org/data/definitions/22.html",
            "cweId": "22",
            "wascId": "4",
        })
        alerts = connector.get_alerts()
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert.rule_id == "30001"
        assert alert.name == "Path Traversal"
        assert alert.risk == "High"
        assert alert.confidence == 4
        assert alert.method == "GET"
        assert alert.parameter == "q"
        assert alert.remediation == "使用白名单校验输入"
        assert alert.cwe_id == 22
        assert alert.wasc_id == 4
        assert alert.reference.endswith("22.html")
        # Confidence 原样保留，不参与 Severity 映射。
        assert alert.confidence == 4
        assert map_zap_risk(alert.risk) == "HIGH"

    def test_alert_evidence_is_redacted(self):
        """验证告警`evidence`是否`redacted`场景及其预期结果。"""
        connector = make_connector()
        connector._state.transport.seed_raw_alert({
            "id": "60103",
            "alert": "Reflected XSS",
            "risk": "Medium",
            "confidence": "4",
            "url": "https://test.example.com/users?q=x",
            "method": "GET",
            "evidence": "Authorization: Bearer " + JWT,
        })
        (alert,) = connector.get_alerts()
        assert JWT not in alert.evidence
        assert REDACTED_PLACEHOLDER in alert.evidence

    def test_alert_url_credentials_are_redacted(self):
        """验证告警URL`credentials`是否为`redacted`场景及其预期结果。"""
        connector = make_connector()
        connector._state.transport.seed_raw_alert({
            "id": "10021",
            "alert": "Server Version Leak",
            "risk": "Informational",
            "confidence": "5",
            "url": f"https://test.example.com/callback?token={JWT}&page=2",
            "method": "GET",
        })
        (alert,) = connector.get_alerts()
        assert JWT not in alert.url
        assert "token=******" in alert.url
        assert "page=2" in alert.url

    def test_alert_confidence_is_preserved_not_merged(self):
        """Confidence 与 Severity 是两个维度，不能被合并或改写。"""
        connector = make_connector()
        connector._state.transport.seed_raw_alert({
            "id": "10021", "alert": "Leak", "risk": "High", "confidence": "1",
            "url": BASE_URL + "/", "method": "GET",
        })
        (alert,) = connector.get_alerts()
        assert alert.confidence == 1
        assert alert.risk == "High"

    def test_alert_counts_group_by_severity(self):
        """验证告警`counts``group`按严重级别场景及其预期结果。"""
        connector = make_connector()
        for risk, rule in (("High", "60001"), ("Medium", "40015"), ("Low", "10010"),
                           ("Informational", "10021"), ("Bogus", "99999")):
            connector._state.transport.seed_raw_alert({
                "id": rule, "alert": "r", "risk": risk, "confidence": "3",
                "url": BASE_URL + "/", "method": "GET",
            })
        counts = connector.get_alert_counts(connector.get_alerts())
        assert counts.as_dict() == {"total": 5, "high": 1, "medium": 2, "low": 1, "info": 1}

    def test_alert_filter_by_rule_ids(self):
        """验证告警筛选条件按规则`ids`场景及其预期结果。"""
        connector = make_connector()
        connector._state.transport.seed_raw_alert({"id": "1", "alert": "A", "risk": "Low", "confidence": "3",
                                            "url": BASE_URL, "method": "GET"})
        connector._state.transport.seed_raw_alert({"id": "2", "alert": "B", "risk": "High", "confidence": "3",
                                            "url": BASE_URL, "method": "GET"})
        only = connector.get_alerts(rule_ids=["2"])
        assert [a.rule_id for a in only] == ["2"]

    def test_statistics_degrade_to_zero_on_missing_endpoint(self):
        """URL / 进度端点缺失不能阻断结果导入——只降级为 0。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.start_spider(BASE_URL)
        connector.wait_passive_scan(5)
        keys = [("GET", "/JSON/core/urls"), ("POST", "/JSON/pscan/progress")]
        saved = {key: _HANDLERS.pop(key) for key in keys}
        try:
            stats, counts = connector.get_scan_statistics()
        finally:
            _HANDLERS.update(saved)
        assert stats.urls == 0
        assert stats.pages == 0
        # 告警本身仍然拿得到，导入不被阻断。
        assert counts.total == len(connector.get_alerts())

    def test_missing_alert_endpoint_fails_result_import(self):
        """alertJson 缺失属于结果导入失败，必须抛错而不是静默返回空结果。"""
        connector = make_connector()
        handler = _HANDLERS.pop(("POST", "/JSON/core/alertJson"))
        try:
            with pytest.raises(ZAPConnectorError):
                connector.get_alerts()
        finally:
            _HANDLERS[("POST", "/JSON/core/alertJson")] = handler

    def test_list_urls_empty_when_endpoint_missing(self):
        """验证列出`urls`空值当接口缺失场景及其预期结果。"""
        connector = make_connector()
        handler = _HANDLERS.pop(("GET", "/JSON/core/urls"))
        try:
            assert connector.list_urls() == []
        finally:
            _HANDLERS[("GET", "/JSON/core/urls")] = handler

    def test_scan_statistics_counts_urls_and_alerts(self):
        """验证扫描`statistics``counts``urls`和`alerts`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.start_spider(BASE_URL)
        connector.wait_passive_scan(5)
        stats, counts = connector.get_scan_statistics()
        assert stats.urls > 0
        assert counts.total == len(connector.get_alerts())

    def test_list_urls_redacts_credentials(self):
        """验证列出`urls``redacts``credentials`场景及其预期结果。"""
        connector = make_connector()
        connector._state.transport._urls.add(f"https://test.example.com/cb?token={JWT}&x=1")
        urls = connector.list_urls()
        assert JWT not in urls[0]
        assert "token=******" in urls[0]
        assert "x=1" in urls[0]

    def test_openapi_import_missing_component_raises(self):
        """验证`openapi``import`缺失`component``raises`场景及其预期结果。"""
        connector = make_connector(MockZAPWorld(base_host=BASE_URL, has_openapi=False))
        with pytest.raises(ZAPConnectorError) as excinfo:
            connector.import_openapi("{}", file_name="spec.json")
        assert excinfo.value.reason == ZAP_REASON_PLUGIN_MISSING

    def test_openapi_import_empty_document_rejected(self):
        """验证`openapi``import`空值`document`被拒绝场景及其预期结果。"""
        with pytest.raises(ZAPConnectorError) as excinfo:
            make_connector().import_openapi("   ")
        assert excinfo.value.reason == ZAP_REASON_CONTEXT_FAILED

    def test_openapi_import_records_upload(self):
        """验证`openapi``import`记录`upload`场景及其预期结果。"""
        connector = make_connector()
        result = connector.import_openapi('{"openapi": "3.0.3"}', file_name="spec.json")
        assert "openapi_id" in result
        assert connector._state.transport.openapi_imports[0]["size"] > 0

    def test_passive_rules_are_listable(self):
        """验证`passive``rules`是否为`listable`场景及其预期结果。"""
        rules = make_connector().list_passive_rules()
        assert rules
        assert all({"rule_id", "description"} <= set(rule) for rule in rules)

    def test_stop_scan_clears_scan_ids(self):
        """验证停止扫描`clears`扫描`ids`场景及其预期结果。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.configure_authentication(bear_auth())
        connector.start_active_scan(BASE_URL, selected_rule_ids=["30001"])
        connector.stop_scan([])
        assert connector._state.scan_ids == []


# --------------------------------------------------------------------------- 契约层工具


class TestContracts:
    def test_risk_mapping_only_goes_down(self):
        """验证风险映射仅`goes``down`场景及其预期结果。"""
        assert map_zap_risk("High") == "HIGH"
        assert map_zap_risk("Medium") == "MEDIUM"
        assert map_zap_risk("Low") == "LOW"
        assert map_zap_risk("Informational") == "INFO"
        # 未识别值落默认，不能凭空造出 CRITICAL。
        assert map_zap_risk("") == "MEDIUM"
        assert map_zap_risk("Critical") == "MEDIUM"

    def test_parse_zap_version(self):
        """验证解析ZAP版本场景及其预期结果。"""
        assert parse_zap_version("2.16.0") == (2, 16, 0)
        assert parse_zap_version("2.11") == (2, 11, 0)
        assert parse_zap_version("x") is None
        assert is_supported_version("2.12.0") is True
        assert is_supported_version("2.11.9") is False
        assert is_supported_version("") is False

    def test_redact_text_bearer_and_cookie(self):
        """验证`redact`文本`bearer`和`cookie`场景及其预期结果。"""
        text = f"Authorization: Bearer {JWT}\nCookie: session=abc; sid=xyz"
        result = redact_text(text)
        assert JWT not in result
        assert "abc" not in result
        assert REDACTED_PLACEHOLDER in result

    def test_redact_url_keeps_non_credential_params(self):
        """验证`redact`URL`keeps``non``credential``params`场景及其预期结果。"""
        result = redact_url(f"{BASE_URL}/cb?token={JWT}&refresh_token=rt&page=3&q=hi")
        assert "token=******" in result
        assert "refresh_token=******" in result
        assert "page=3" in result
        assert "q=hi" in result
        assert JWT not in result

    def test_redact_url_without_query_is_untouched(self):
        """验证`redact`URL不带查询参数是否`untouched`场景及其预期结果。"""
        assert redact_url(BASE_URL) == BASE_URL
        assert redact_url("") == ""

    def test_mock_rejects_unknown_endpoint(self):
        """新增 ZAP 调用必须先登记到 Mock，否则会立刻失败——防止静默漂移。"""
        with pytest.raises(ZAPTransportError) as excinfo:
            make_mock().request(method="GET", path="/JSON/core/notExists")
        assert excinfo.value.status_code == 404
        assert "未实现端点" in excinfo.value.message

    def test_mock_closed_transport_raises(self):
        """验证模拟`closed``transport``raises`场景及其预期结果。"""
        transport = make_mock()
        transport.close()
        with pytest.raises(ZAPTransportError):
            transport.request(method="GET", path="/JSON/core/about")

    def test_mock_drops_credential_query_params_in_alert_urls(self):
        """告警 URL 里带凭据参数时，ZAP 侧与 Connector 侧都必须抹掉值。"""
        connector = make_connector()
        apply_default_scope(connector)
        world = connector._state.transport.world
        world.endpoints.append(MockEndpoint("/cb", query_params=["token"],
                                           passive_rule_ids=[10021]))
        connector.start_spider(BASE_URL)
        alerts = connector.get_alerts()
        url_alerts = [a for a in alerts if "/cb" in a.url]
        assert url_alerts
        assert all(MOCK_TOKEN_VALUE not in a.url for a in url_alerts)
        assert all("token=******" in a.url for a in url_alerts)


class TestMockWorldConfig:
    def test_world_without_client_spider_addon(self):
        """验证`world`不带客户端爬虫`addon`场景及其预期结果。"""
        world = MockZAPWorld(base_host=BASE_URL, has_client_spider=False)
        assert world.has_client_spider is False

    def test_world_custom_rules_can_disable_rules(self):
        """验证`world`自定义`rules`可以`disable``rules`场景及其预期结果。"""
        rules = [MockRule(1, "OnlyRule", "Low", 3, category="pscan", enabled=True)]
        world = MockZAPWorld(base_host=BASE_URL, rules=rules)
        transport = MockZAPTransport(world)
        assert transport.pscan_enabled == {"1"}

    def test_mock_world_does_not_send_any_real_request(self):
        """Mock 全程不发出站请求——这一点在单元测试层面是不可违反的前提。"""
        connector = make_connector()
        apply_default_scope(connector)
        connector.start_spider(BASE_URL)
        connector.wait_passive_scan(5)
        connector.start_active_scan(BASE_URL, selected_rule_ids=["30001"])
        connector.get_alerts()
        connector.stop_scan([])
        connector.clean_scan_context()
        # 没有 httpx 客户端被创建，也就没有出站连接。
        assert connector._state.transport.fail_with is None
