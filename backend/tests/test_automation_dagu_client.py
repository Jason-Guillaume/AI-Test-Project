"""Dagu REST client contract and security coverage."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.features.automation_center.providers.base import ProviderError
from app.features.automation_center.providers.dagu_client import DaguClient
from app.features.automation_center.schemas import IntegrationCreate


def test_dagu_client_auth_routes_run_logs_and_redaction():
    """Use the Dagu REST paths, bearer header, stable run ID, and bounded log contract."""
    api_key = "dagu_test_private_api_key"
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path.startswith("/api/v1/")
        assert request.headers["authorization"] == f"Bearer {api_key}"
        if request.url.path.endswith("/openapi.json"):
            return httpx.Response(200, json={"info": {"version": "1.2.3"}}, request=request)
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json={"status": "ok", "version": "1.2.3"}, request=request)
        if request.url.path.endswith("/dags"):
            return httpx.Response(200, json={"dags": [{"fileName": "automation-pytest-allure"}]}, request=request)
        if request.url.path.endswith("/spec"):
            return httpx.Response(200, json={"name": "automation-pytest-allure"}, request=request)
        if request.method == "POST" and request.url.path.endswith("/enqueue"):
            body = json.loads(request.content)
            assert body["dagRunId"] == "automation-42"
            assert json.loads(body["params"])["branch"] == "main"
            return httpx.Response(200, json={"dagRunId": body["dagRunId"], "statusLabel": "queued"}, request=request)
        if request.url.path.endswith("/log"):
            return httpx.Response(200, json={"content": f"token={api_key}\npassword=hunter2"}, request=request)
        if request.method == "POST" and request.url.path.endswith("/stop"):
            return httpx.Response(204, request=request)
        if request.url.path.endswith("/dequeue"):
            return httpx.Response(200, content=b"", request=request)
        return httpx.Response(404, request=request)

    client = DaguClient(
        "https://dagu.example.com/api/v1", api_key,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client.get_openapi()["info"]["version"] == "1.2.3"
        assert client.get_health()["version"] == "1.2.3"
        assert client.list_dags() == [{"fileName": "automation-pytest-allure"}]
        assert client.get_dag_spec("automation-pytest-allure")["name"] == "automation-pytest-allure"
        run = client.enqueue("automation-pytest-allure", {"branch": "main"}, "automation-42", "automation-tests")
        assert run["dagRunId"] == "automation-42"
        log = client.get_log("automation-pytest-allure", "automation-42", limit=2000)
        assert api_key not in log
        assert "password=***" in log
        client.stop("automation-pytest-allure", "automation-42")
        client.dequeue("automation-pytest-allure", "automation-42")
        assert any(item.url.path.endswith("/dag-runs/automation-pytest-allure/automation-42/stop") for item in requests)
        assert all(item.url.scheme == "https" for item in requests)
    finally:
        client.close()


@pytest.mark.parametrize("address", [
    "http://dagu.example.com:45394",
    "http://8.8.8.8:45394",
])
def test_public_http_dagu_endpoint_is_rejected(address: str):
    """Never send Dagu bearer credentials to a public host over plain HTTP."""
    with pytest.raises(ProviderError, match="公网 HTTP"):
        DaguClient(address, "dagu_test_private_api_key")


def test_private_http_requires_explicit_opt_in_and_safe_url(monkeypatch):
    """Permit controlled private HTTP only after explicit service configuration and host allowlisting."""
    monkeypatch.setattr(settings, "DAGU_PRIVATE_HOST_ALLOWLIST", "")
    with pytest.raises(ProviderError, match="公网 HTTP"):
        DaguClient("http://127.0.0.1:45394", "dagu_test_private_api_key", allow_insecure_http=True)
    monkeypatch.setattr(settings, "DAGU_PRIVATE_HOST_ALLOWLIST", "127.0.0.1")
    client = DaguClient(
        "http://127.0.0.1:45394", "dagu_test_private_api_key",
        allow_insecure_http=True, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={}, request=request)),
    )
    client.close()
    monkeypatch.setattr(settings, "DAGU_PRIVATE_HOST_ALLOWLIST", "10.0.0.8")
    with pytest.raises(ProviderError, match="未授权的内网"):
        DaguClient(
            "https://10.1.1.1", "dagu_test_private_api_key",
            resolver=lambda *_args, **_kwargs: [(None, None, None, None, ("169.254.169.254", 0))],
        )
    with pytest.raises(ProviderError, match="路径"):
        DaguClient("https://dagu.example.com/another-path", "dagu_test_private_api_key")


def test_integration_schema_requires_https_or_admin_enabled_private_http(monkeypatch):
    """Apply the same public-HTTP restriction before API credentials are persisted."""
    payload = {
        "provider_type": "DAGU", "name": "test", "dagu_api_key": "dagu_test_private_api_key",
        "callback_secret": "callback-secret-value",
    }
    monkeypatch.setattr(settings, "DAGU_ALLOW_INSECURE_HTTP", False)
    with pytest.raises(ValidationError, match="公网 HTTP"):
        IntegrationCreate(**{**payload, "dagu_base_url": "http://10.0.0.8:45394"})
    monkeypatch.setattr(settings, "DAGU_ALLOW_INSECURE_HTTP", True)
    monkeypatch.setattr(settings, "DAGU_PRIVATE_HOST_ALLOWLIST", "10.0.0.8")
    IntegrationCreate(**{**payload, "dagu_base_url": "http://10.0.0.8:45394"})
    with pytest.raises(ValidationError, match="公网 HTTP"):
        IntegrationCreate(**{**payload, "dagu_base_url": "http://10.1.1.1:45394"})
    with pytest.raises(ValidationError, match="公网 HTTP"):
        IntegrationCreate(**{**payload, "dagu_base_url": "http://gold1.mczbc.cn:45394"})


def test_redirect_and_auth_failures_never_leak_api_key():
    """Return safe errors for redirects and denied API credentials."""
    def redirect(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://attacker.example/collect"})

    client = DaguClient("https://dagu.example.com", "dagu_test_private_api_key", transport=httpx.MockTransport(redirect))
    try:
        with pytest.raises(ProviderError, match="重定向"):
            client.get_health()
    finally:
        client.close()

    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request)

    client = DaguClient("https://dagu.example.com", "dagu_test_private_api_key", transport=httpx.MockTransport(denied))
    try:
        with pytest.raises(ProviderError, match="认证失败") as error:
            client.get_health()
        assert "dagu_test_private_api_key" not in str(error.value)
    finally:
        client.close()
