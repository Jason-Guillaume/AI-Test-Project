"""Small, secret-safe HTTP client for the Dagu REST API."""

from __future__ import annotations

import json
import ipaddress
import re
from urllib.parse import quote, urlsplit

import httpx

from app.features.automation_center.providers.base import ProviderError

_MAX_LOG_BYTES = 200_000
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(token|secret|password|authorization|credential|api[_-]?key|private[_-]?key)\s*[:=]\s*\S+",
)


class DaguClient:
    """Dagu REST client. Redirects, ambient proxies, and TLS verification bypasses are disabled."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: httpx.Timeout | float = httpx.Timeout(connect=5, read=20, write=10, pool=5),
        transport: httpx.BaseTransport | None = None,
        allow_insecure_http: bool = False,
    ) -> None:
        """创建禁用重定向与环境代理的客户端，并把 API Key 仅放入认证头。"""
        self.base_url = self.normalize_base_url(base_url, allow_insecure_http=allow_insecure_http)
        self._api_key = api_key.strip()
        if len(self._api_key) < 8:
            raise ProviderError("Dagu API Key 未配置或格式无效")
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
            timeout=timeout,
            verify=True,
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    @staticmethod
    def normalize_base_url(value: str, *, allow_insecure_http: bool = False) -> str:
        """保留部署的 HTTP/HTTPS 协议，并限制地址路径及 URL 凭证字段。"""
        parsed = urlsplit((value or "").strip().rstrip("/"))
        if (
            parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment
        ):
            raise ProviderError("Dagu API 地址必须使用 HTTP/HTTPS，且不能包含账号、密码、查询参数或片段")
        if parsed.path not in {"", "/", "/api/v1"}:
            raise ProviderError("Dagu API 地址路径只允许为空或 /api/v1")
        if parsed.scheme == "http" and not (
            allow_insecure_http and DaguClient._is_controlled_private_http_host(parsed.hostname)
        ):
            raise ProviderError("Dagu API Key 禁止通过公网 HTTP 传输；请配置 HTTPS 或受控私网地址")
        origin = f"{parsed.scheme.lower()}://{parsed.netloc}"
        return origin + "/api/v1"

    @staticmethod
    def _is_controlled_private_http_host(hostname: str) -> bool:
        """仅把本机、私有 IP 和明确的内部 DNS 后缀视为受控 HTTP 地址。"""
        host = hostname.lower().rstrip(".")
        try:
            address = ipaddress.ip_address(host)
            return address.is_private or address.is_loopback or address.is_link_local
        except ValueError:
            return host == "localhost" or host.endswith((".localhost", ".internal", ".local"))

    def close(self) -> None:
        """关闭 HTTP 连接池，释放 Provider 生命周期内占用的连接。"""
        self._client.close()

    def list_dags(self) -> list[dict]:
        """分页读取当前凭证可访问的 DAG，并兼容不同版本的响应封装。"""
        result: list[dict] = []
        page = 1
        valid_response = False
        while page <= 20:
            payload = self._request("GET", "/dags", params={"page": page, "perPage": 1000})
            if isinstance(payload, list):
                valid_response = True
                result.extend(item for item in payload if isinstance(item, dict))
                break
            if not isinstance(payload, dict):
                break
            items = next((payload.get(key) for key in ("dags", "items", "data") if isinstance(payload.get(key), list)), None)
            if items is None:
                break
            valid_response = True
            result.extend(item for item in items if isinstance(item, dict))
            pagination = payload.get("pagination")
            total_pages = pagination.get("totalPages") if isinstance(pagination, dict) else None
            if not isinstance(total_pages, int) or page >= total_pages or len(items) < 1000:
                break
            page += 1
        if valid_response:
            return result
        raise ProviderError("Dagu DAG 列表响应格式无效")

    def get_openapi(self) -> dict:
        """读取 Dagu 实例实际提供的 OpenAPI 文档。"""
        payload = self._request("GET", "/openapi.json")
        if not isinstance(payload, dict):
            raise ProviderError("Dagu OpenAPI 响应格式无效")
        return payload

    def get_health(self) -> dict:
        """查询 Dagu 健康端点并读取服务实际版本。"""
        payload = self._request("GET", "/health")
        if not isinstance(payload, dict):
            raise ProviderError("Dagu Health 响应格式无效")
        return payload

    def get_dag_spec(self, dag_name: str) -> dict:
        """读取指定 DAG 文件名对应的解析后定义。"""
        payload = self._request("GET", f"/dags/{quote(dag_name, safe='')}/spec")
        if not isinstance(payload, dict):
            raise ProviderError("Dagu DAG Spec 响应格式无效")
        return payload

    def enqueue(self, dag_name: str, params: dict, dag_run_id: str, queue: str) -> dict:
        """用稳定 dagRunId 入队，并按 Dagu 合约把参数序列化为 JSON 字符串。"""
        body = {
            "params": json.dumps(params, ensure_ascii=False, separators=(",", ":")),
            "dagRunId": dag_run_id,
            "queue": queue,
        }
        payload = self._request("POST", f"/dags/{quote(dag_name, safe='')}/enqueue", json=body)
        return payload if isinstance(payload, dict) else {"dagRunId": dag_run_id}

    def get_run(self, dag_name: str, dag_run_id: str) -> dict:
        """读取运行详情并解包不同 Dagu 版本使用的外层响应字段。"""
        payload = self._request(
            "GET", f"/dag-runs/{quote(dag_name, safe='')}/{quote(dag_run_id, safe='')}"
        )
        if isinstance(payload, dict):
            for key in ("dagRunDetails", "dagRun", "data"):
                if isinstance(payload.get(key), dict):
                    payload = payload[key]
                    break
        if not isinstance(payload, dict):
            raise ProviderError("Dagu DAG Run 响应格式无效")
        return payload

    def list_runs(self, dag_name: str, *, limit: int = 10) -> list[dict]:
        """读取指定 DAG 的运行历史，并将返回数限制在调用方要求的数量内。"""
        payload = self._request("GET", f"/dags/{quote(dag_name, safe='')}/dag-runs")
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)][:max(1, min(limit, 1000))]
        if isinstance(payload, dict):
            for key in ("dagRuns", "runs", "items", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)][:max(1, min(limit, 1000))]
        raise ProviderError("Dagu DAG Run 列表响应格式无效")

    def get_log(
        self,
        dag_name: str,
        dag_run_id: str,
        *,
        tail: int | None = None,
        head: int | None = None,
        offset: int | None = None,
        limit: int = _MAX_LOG_BYTES,
    ) -> str:
        """读取 Dagu 日志内容，按行数和最终字节数双重限幅并遮蔽凭证。"""
        limit_bytes = max(1, min(int(limit), _MAX_LOG_BYTES))
        # Dagu's API limit is a line count (capped at 10,000), not a byte count.
        line_limit = min(10_000, max(1, (limit_bytes + 199) // 200))
        params = {key: value for key, value in {
            "tail": min(tail, 10_000) if tail is not None else None,
            "head": min(head, 10_000) if head is not None else None,
            "offset": offset,
            "limit": line_limit,
        }.items() if value is not None}
        payload = self._request(
            "GET", f"/dag-runs/{quote(dag_name, safe='')}/{quote(dag_run_id, safe='')}/log",
            params=params,
        )
        if isinstance(payload, dict):
            payload = payload.get("log") or payload.get("content") or ""
        return self.redact(str(payload))[-limit_bytes:]

    def stop(self, dag_name: str, dag_run_id: str) -> None:
        """请求 Dagu 停止运行中的 DAG。"""
        self._request("POST", f"/dag-runs/{quote(dag_name, safe='')}/{quote(dag_run_id, safe='')}/stop", allow_empty=True)

    def dequeue(self, dag_name: str, dag_run_id: str) -> None:
        """从 Dagu 队列中移除尚未启动的 DAG Run。"""
        self._request("GET", f"/dag-runs/{quote(dag_name, safe='')}/{quote(dag_run_id, safe='')}/dequeue", allow_empty=True)

    def _request(self, method: str, path: str, *, allow_empty: bool = False, **kwargs):
        """发起 Dagu API 请求，处理网络错误并拒绝重定向和非预期响应。"""
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ProviderError("Dagu API 请求超时") from exc
        except httpx.RequestError as exc:
            raise ProviderError("无法连接 Dagu API") from exc
        if 300 <= response.status_code < 400:
            raise ProviderError("Dagu API 返回重定向，已拒绝访问", response.status_code)
        if response.is_error:
            messages = {
                401: "Dagu API Key 认证失败",
                403: "Dagu API Key 权限不足",
                404: "Dagu DAG 或运行实例不存在",
            }
            raise ProviderError(
                messages.get(response.status_code, f"Dagu API 请求失败（HTTP {response.status_code}）"),
                response.status_code,
            )
        if allow_empty and (response.status_code == 204 or not response.content):
            return {}
        try:
            return response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("Dagu API 返回了无效 JSON") from exc

    def redact(self, value: str) -> str:
        """从外部日志中移除当前 API Key、常见凭证赋值和 NUL 字符。"""
        cleaned = value.replace("\x00", "")
        if self._api_key:
            cleaned = cleaned.replace(self._api_key, "***")
        return _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=***", cleaned)
