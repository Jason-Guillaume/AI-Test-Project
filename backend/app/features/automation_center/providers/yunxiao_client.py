"""云效 Flow OpenAPI 客户端。

对接中心版与 Region 版的运行、查询和终止接口。令牌只放在请求头，不进入异常文本。
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class YunxiaoError(Exception):
    """云效调用失败。message 已去掉令牌，可以返回给调用方。"""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


def http_client(timeout: float) -> httpx.Client:
    """创建不继承环境代理的 HTTP 客户端。测试可替换此函数。"""
    return httpx.Client(timeout=timeout, trust_env=False)


def _safe_id(value: str, label: str) -> str:
    """限制路径参数字符，避免把标识拼进 URL 时改变路径。"""
    if not _ID.fullmatch(value or ""):
        raise YunxiaoError(f"{label}不合法")
    return value


class YunxiaoClient:
    """云效流水线运行客户端。"""

    def __init__(
        self, *, base_url: str, token: str, organization_id: str, deployment: str, timeout: float = 20,
    ):
        self._base_url = (base_url or "").rstrip("/")
        self._token = token
        self._organization_id = organization_id or ""
        self._deployment = deployment if deployment in {"central", "region"} else "central"
        self._timeout = timeout

    def __repr__(self) -> str:
        return "YunxiaoClient(redacted)"

    def list_runs(self, pipeline_id: str, *, per_page: int = 10) -> list[dict[str, Any]]:
        """读取最近的流水线运行。用于连通性检查和提交触发的反向同步。"""
        payload = self._request(
            "GET", f"{self._root(pipeline_id)}/runs",
            params={"perPage": max(1, min(per_page, 30)), "page": 1},
        )
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            runs = payload.get("pipelineRuns") or payload.get("items") or []
            return [item for item in runs if isinstance(item, dict)]
        return []

    def create_run(self, pipeline_id: str, params: dict[str, Any]) -> str:
        """触发流水线。官方接口把运行参数作为 JSON 字符串放在 params 字段。"""
        payload = self._request(
            "POST", f"{self._root(pipeline_id)}/runs",
            json_body={"params": json.dumps(params, ensure_ascii=False, separators=(",", ":"))},
        )
        if isinstance(payload, int):
            return str(payload)
        if isinstance(payload, str) and payload.strip().isdigit():
            return payload.strip()
        if isinstance(payload, dict):
            run_id = payload.get("pipelineRunId") or payload.get("id")
            if run_id is not None:
                return str(run_id)
        raise YunxiaoError("云效未返回流水线运行实例 ID")

    def get_run(self, pipeline_id: str, pipeline_run_id: str) -> dict[str, Any]:
        """查询单次运行实例。"""
        payload = self._request(
            "GET", f"{self._root(pipeline_id)}/runs/{_safe_id(str(pipeline_run_id), '运行实例 ID')}",
        )
        if not isinstance(payload, dict):
            raise YunxiaoError("云效运行实例响应无法解析")
        return payload

    def stop_run(self, pipeline_id: str, pipeline_run_id: str) -> bool:
        """终止运行实例。云效返回布尔值。"""
        payload = self._request(
            "PUT", f"{self._root(pipeline_id)}/runs/{_safe_id(str(pipeline_run_id), '运行实例 ID')}",
        )
        return payload is True or payload == "true"

    def _root(self, pipeline_id: str) -> str:
        """按部署形态拼官方流水线路径。"""
        pipeline = _safe_id(str(pipeline_id), "流水线 ID")
        if self._deployment == "region":
            return f"/oapi/v1/flow/pipelines/{pipeline}"
        organization = _safe_id(self._organization_id, "企业 ID")
        return f"/oapi/v1/flow/organizations/{organization}/pipelines/{pipeline}"

    def _request(self, method: str, path: str, *, params: dict | None = None, json_body: dict | None = None) -> Any:
        """发送请求。失败信息只保留云效的 errorMessage，不记录请求头。"""
        if not self._base_url.startswith("https://"):
            raise YunxiaoError("云效 API 地址必须使用 HTTPS")
        if not self._token:
            raise YunxiaoError("云效访问令牌未配置")
        try:
            with http_client(self._timeout) as client:
                response = client.request(
                    method, f"{self._base_url}{path}", params=params, json=json_body,
                    headers={"x-yunxiao-token": self._token, "Content-Type": "application/json"},
                )
        except httpx.HTTPError as exc:
            raise YunxiaoError(f"云效网络异常：{exc.__class__.__name__}") from exc
        if response.status_code >= 400:
            raise YunxiaoError(self._safe_error(response), response.status_code)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            text = response.text.strip()
            if text.isdigit():
                return int(text)
            raise YunxiaoError("云效响应无法解析") from None

    @staticmethod
    def _safe_error(response: httpx.Response) -> str:
        """提取可展示的失败原因。"""
        message = ""
        try:
            payload = response.json()
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            message = str(payload.get("errorMessage") or payload.get("message") or payload.get("msg") or "")
        message = message.replace("\n", " ")[:180]
        if not message:
            message = "云效拒绝了请求"
        return f"云效接口失败（HTTP {response.status_code}）：{message}"
