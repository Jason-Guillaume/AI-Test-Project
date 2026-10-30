"""共享能力迁移的离线行为回归。

这些用例固定表达式领域差异、模板解析边界和 HTTP 发送策略，不连接数据库或真实外部服务。
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

import app.execution.http.executor as http_executor
from app.core.expressions.operators import evaluate_operator
from app.core.expressions.paths import extract_dot_path, extract_jsonpath
from app.core.http.errors import AppError
from app.execution.templates.resolver import ResolveScope, resolve_template
from app.features.business.executors.precondition_evaluator import evaluate_preconditions


class _FakeResponse:
    """为共享发送循环提供确定性响应数据。"""

    def __init__(self, body: bytes) -> None:
        """初始化成功响应及请求 URL。"""
        self.status_code = 201
        self.headers = {"Content-Type": "text/plain"}
        self.request = SimpleNamespace(url="https://api.example.test/resource?q=1")
        self.body = body

    def iter_bytes(self, *, chunk_size: int):
        """按 httpx 流式接口分块返回测试响应。"""
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset:offset + chunk_size]


class _ResponseContext:
    """模拟 httpx 响应的上下文管理器。"""

    def __init__(self, response: _FakeResponse) -> None:
        """保存要返回的假响应。"""
        self.response = response

    def __enter__(self) -> _FakeResponse:
        """返回响应对象。"""
        return self.response

    def __exit__(self, *exc_info: Any) -> bool:
        """不吞掉发送过程中的异常。"""
        return False


class _FakeClient:
    """记录发送参数并返回可控的流式响应。"""

    def __init__(self, response: _FakeResponse, **options: Any) -> None:
        """保存客户端安全选项和响应替身。"""
        self.options = options
        self.response = response
        self.request: dict[str, Any] = {}

    def __enter__(self) -> "_FakeClient":
        """返回客户端替身。"""
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        """不吞掉客户端上下文异常。"""
        return False

    def stream(self, method: str, url: str, **kwargs: Any) -> _ResponseContext:
        """记录发送调用并返回假响应上下文。"""
        self.request = {"method": method, "url": url, **kwargs}
        return _ResponseContext(self.response)


def test_shared_http_sender_keeps_security_and_request_options(monkeypatch):
    """共享发送器固定代理、重定向、超时、请求覆盖和响应字段。"""
    captured = {}
    original_client = http_executor.httpx.AsyncClient

    def handler(request):
        captured["request"] = request
        return httpx.Response(201, text="created", headers={"Content-Type": "text/plain"})

    def create_client(**options):
        captured["options"] = options
        return original_client(transport=httpx.MockTransport(handler), **options)

    monkeypatch.setattr(http_executor.httpx, "AsyncClient", create_client)

    result = http_executor.send_http_request(
        method="post",
        url="https://api.example.test/resource",
        headers={"X-Test": "yes"},
        query={"q": "1"},
        json_body={"value": 3},
        timeout=4,
    )

    assert captured["options"]["trust_env"] is False
    assert captured["options"]["follow_redirects"] is False
    assert captured["options"]["timeout"].connect == 4
    request = captured["request"]
    assert request.method == "POST"
    assert request.headers["X-Test"] == "yes"
    assert request.url.params["q"] == "1"
    assert request.content == b'{"value":3}'
    assert result.status_code == 201
    assert result.request_url == "https://api.example.test/resource?q=1"
    assert result.response_body == "created"


def test_shared_http_sender_truncates_streamed_body(monkeypatch):
    """共享发送器在超过响应上限时保留既有截断标记。"""
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        http_executor.httpx,
        "AsyncClient",
        lambda **options: original_client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(200, content=b"x" * 200_001),
            ),
            **options,
        ),
    )

    result = http_executor.send_http_request(method="GET", url="https://api.example.test/large")

    assert result.response_body == "x" * 200_000 + "\n...[已截断]"


def test_shared_http_sender_can_preserve_explicit_json_null(monkeypatch):
    """调试接口的显式 JSON null 经 body builder 后仍作为请求体发送。"""
    from app.features.api_catalog.services.debug_service import DebugService

    send_kwargs = DebugService()._build_send_kwargs(
        SimpleNamespace(body_type="json", raw_text="null", schema_json=None),
        SimpleNamespace(override_body=None),
    )
    assert "json" in send_kwargs and send_kwargs["json"] is None

    captured = {}
    original_client = http_executor.httpx.AsyncClient

    def handler(request):
        captured["request"] = request
        return httpx.Response(200, content=b"ok")

    monkeypatch.setattr(
        http_executor.httpx,
        "AsyncClient",
        lambda **options: original_client(transport=httpx.MockTransport(handler), **options),
    )
    http_executor.send_http_request(
        method="POST",
        url="https://api.example.test/resource",
        json_body=send_kwargs.get("json"),
        json_body_present="json" in send_kwargs,
    )

    assert captured["request"].content == b"null"
    assert captured["request"].headers["content-type"] == "application/json"


def test_shared_http_sender_preserves_multibyte_utf8_across_chunk_boundary(monkeypatch):
    """UTF-8 字符跨 65,536 字节传输块时，在拼接后整体解码。"""
    body = b"a" * 65_535 + "中".encode("utf-8")
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        http_executor.httpx,
        "AsyncClient",
        lambda **options: original_client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=body)),
            **options,
        ),
    )

    result = http_executor.send_http_request(method="GET", url="https://api.example.test/utf8")

    assert result.response_body == "a" * 65_535 + "中"


def test_shared_http_sender_replaces_invalid_utf8_after_combining_chunks(monkeypatch):
    """合并响应字节后保留无效 UTF-8 的替换解码语义。"""
    body = b"a" * 65_535 + b"\xff"
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        http_executor.httpx,
        "AsyncClient",
        lambda **options: original_client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=body)),
            **options,
        ),
    )

    result = http_executor.send_http_request(method="GET", url="https://api.example.test/invalid-utf8")

    assert result.response_body == "a" * 65_535 + "\ufffd"


def test_shared_http_sender_total_timeout_cancels_and_closes_slow_stream(monkeypatch):
    """总时限覆盖持续慢速响应，且超时取消会关闭响应流。"""
    class SlowStream(httpx.AsyncByteStream):
        def __init__(self):
            self.closed = False

        async def __aiter__(self):
            while True:
                await asyncio.sleep(0.04)
                yield b"x"

        async def aclose(self):
            self.closed = True

    stream = SlowStream()
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        http_executor.httpx,
        "AsyncClient",
        lambda **options: original_client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, stream=stream)),
            **options,
        ),
    )

    started = time.perf_counter()
    result = http_executor.send_http_request(
        method="GET", url="https://api.example.test/slow", timeout=0.13,
    )

    assert time.perf_counter() - started < 0.4
    assert result.transport_error_kind == "timeout"
    assert result.status_code == 200
    assert stream.closed is True


def test_shared_http_sender_total_timeout_includes_response_headers(monkeypatch):
    """总时限也限制等待响应头，不只限制响应体读取。"""
    async def slow_headers(_request):
        await asyncio.sleep(0.2)
        return httpx.Response(200, content=b"late")

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        http_executor.httpx,
        "AsyncClient",
        lambda **options: original_client(
            transport=httpx.MockTransport(slow_headers), **options,
        ),
    )

    result = http_executor.send_http_request(
        method="GET", url="https://api.example.test/slow-headers", timeout=0.05,
    )

    assert result.transport_error_kind == "timeout"
    assert result.status_code == 0


def test_sync_http_sender_can_run_inside_an_existing_event_loop(monkeypatch):
    """同步发送器被异步调用方使用时仍以独立循环完成并返回。"""
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        http_executor.httpx,
        "AsyncClient",
        lambda **options: original_client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200, content=b"ok")),
            **options,
        ),
    )

    async def invoke_from_async_context():
        return http_executor.send_http_request(
            method="GET", url="https://api.example.test/async-caller",
        )

    result = asyncio.run(invoke_from_async_context())

    assert result.status_code == 200
    assert result.response_body == "ok"


def test_shared_path_readers_keep_supported_dictionary_and_array_subset():
    """共享路径读取保留字典点路径、数组索引和缺失返回 None。"""
    body = {"data": {"items": [{"name": "first"}]}}
    assert extract_jsonpath(body, "$.data.items[0].name") == "first"
    assert extract_jsonpath(body, "$.data.items[2].name") is None
    assert extract_dot_path(body, "data.items") == [{"name": "first"}]
    assert extract_dot_path(body, "data.missing") is None


def test_business_and_test_comparisons_keep_distinct_semantics():
    """业务前置条件与测试/Web 比较保留 None、空 IN 项和未知操作符差异。"""
    assert evaluate_operator(None, "", "EQ") is True
    assert evaluate_operator("", "", "IN") is False
    assert evaluate_operator("same", "same", "UNSUPPORTED") is True

    _, none_passed = evaluate_preconditions(
        [{"target": "value", "operator": "EQ", "expected_value": None}],
        {"value": None},
    )
    _, empty_in_passed = evaluate_preconditions(
        [{"target": "value", "operator": "IN", "expected_value": ""}],
        {"value": ""},
    )
    _, unknown_passed = evaluate_preconditions(
        [{"target": "value", "operator": "UNSUPPORTED", "expected_value": "same"}],
        {"value": "same"},
    )
    assert none_passed is False
    assert empty_in_passed is True
    assert unknown_passed is False


def test_template_resolver_keeps_type_and_required_behavior():
    """迁移后的唯一模板引擎保留整段类型、混合字符串与 required 缺失规则。"""
    scope = ResolveScope(variables={"count": 7})
    assert resolve_template("${runtime.count}", scope) == 7
    assert resolve_template("count=${runtime.count}", scope) == "count=7"
    assert resolve_template("${runtime.missing}", scope) == ""
    with pytest.raises(AppError, match="必需"):
        resolve_template("${runtime.missing}", scope, required=True)


def test_main_registers_zap_management_routes_by_method_and_path():
    """应用装配保留 ZAP 健康、目标与扫描任务的关键 method/path。"""
    from app.main import app

    # FastAPI 近期版本会以 _IncludedRouter 延迟展开 include_router；OpenAPI
    # 是实际挂载后的公共路由表，能覆盖这些延迟路由。
    registered = {
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    required = {
        ("GET", "/api/v1/security/zap/health"),
        ("GET", "/api/v1/security/zap/capabilities"),
        ("GET", "/api/v1/projects/{project_id}/security/scan-targets"),
        ("POST", "/api/v1/projects/{project_id}/security/scan-targets"),
        ("POST", "/api/v1/projects/{project_id}/security/scan-jobs/plan"),
        ("POST", "/api/v1/projects/{project_id}/security/scan-jobs"),
        ("GET", "/api/v1/projects/{project_id}/security/scan-jobs"),
    }
    assert required <= registered


class _LifecycleWorker:
    """记录应用生命周期对 Worker 的启动和关闭调用。"""

    def __init__(self, name: str, events: list[str], *, fail_start: bool = False) -> None:
        """保存事件列表和可选的启动故障。"""
        self.name = name
        self.events = events
        self.fail_start = fail_start

    def start(self) -> None:
        """记录启动，并可模拟已进入启动过程后失败。"""
        self.events.append(f"{self.name}.start")
        if self.fail_start:
            raise RuntimeError("模拟 Worker 启动失败")

    def stop(self) -> None:
        """记录关闭调用。"""
        self.events.append(f"{self.name}.stop")


def test_main_lifespan_starts_and_stops_zap_worker(monkeypatch):
    """ZAP 启用时由应用唯一启动 Worker，退出时反向释放所有 Worker。"""
    import app.main as main_module

    events: list[str] = []
    monkeypatch.setattr(main_module.settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(main_module.settings, "ZAP_ENABLED", True)
    monkeypatch.setattr(main_module, "configure_logging", lambda: None)
    monkeypatch.setattr(main_module, "task_worker", _LifecycleWorker("task", events))
    monkeypatch.setattr(main_module, "scan_worker", _LifecycleWorker("scan", events))
    monkeypatch.setattr(main_module, "flush_langfuse", lambda: None)
    monkeypatch.setattr(main_module, "engine", SimpleNamespace(dispose=lambda: None))
    from app.execution.browser import session_manager
    monkeypatch.setattr(session_manager.registry, "close_all", lambda: None)

    async def exercise():
        """进入并正常退出应用 lifespan。"""
        async with main_module.lifespan(main_module.app):
            pass

    asyncio.run(exercise())
    assert events == ["task.start", "scan.start", "scan.stop", "task.stop"]


def test_main_lifespan_does_not_start_zap_worker_when_disabled(monkeypatch):
    """关闭 ZAP 配置时不启动也不停止扫描 Worker。"""
    import app.main as main_module

    events: list[str] = []
    monkeypatch.setattr(main_module.settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(main_module.settings, "ZAP_ENABLED", False)
    monkeypatch.setattr(main_module, "configure_logging", lambda: None)
    monkeypatch.setattr(main_module, "task_worker", _LifecycleWorker("task", events))
    monkeypatch.setattr(main_module, "scan_worker", _LifecycleWorker("scan", events))
    monkeypatch.setattr(main_module, "flush_langfuse", lambda: None)
    monkeypatch.setattr(main_module, "engine", SimpleNamespace(dispose=lambda: None))
    from app.execution.browser import session_manager
    monkeypatch.setattr(session_manager.registry, "close_all", lambda: None)

    async def exercise():
        """进入并正常退出应用 lifespan。"""
        async with main_module.lifespan(main_module.app):
            pass

    asyncio.run(exercise())
    assert events == ["task.start", "task.stop"]


def test_main_lifespan_releases_workers_after_partial_startup(monkeypatch):
    """扫描 Worker 启动异常时仍关闭已启动和部分启动的 Worker。"""
    import app.main as main_module

    events: list[str] = []
    monkeypatch.setattr(main_module.settings, "AUTO_CREATE_SCHEMA", False)
    monkeypatch.setattr(main_module.settings, "ZAP_ENABLED", True)
    monkeypatch.setattr(main_module, "configure_logging", lambda: None)
    monkeypatch.setattr(main_module, "task_worker", _LifecycleWorker("task", events))
    monkeypatch.setattr(main_module, "scan_worker", _LifecycleWorker("scan", events, fail_start=True))
    monkeypatch.setattr(main_module, "flush_langfuse", lambda: None)
    monkeypatch.setattr(main_module, "engine", SimpleNamespace(dispose=lambda: None))
    from app.execution.browser import session_manager
    monkeypatch.setattr(session_manager.registry, "close_all", lambda: None)

    async def exercise():
        """进入并退出一个会在 Worker 启动阶段失败的 lifespan。"""
        async with main_module.lifespan(main_module.app):
            pass

    with pytest.raises(RuntimeError, match="Worker 启动失败"):
        asyncio.run(exercise())
    assert events == ["task.start", "scan.start", "scan.stop", "task.stop"]
