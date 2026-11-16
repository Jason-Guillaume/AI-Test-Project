"""Dagu adapter for the common automation execution contract."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.config import settings
from app.core.security.crypto import decrypt_secret
from app.features.automation_center.models.entities import AutomationIntegrationConfig
from app.features.automation_center.providers.base import (
    ProviderConnectionResult,
    ProviderError,
    ProviderExecution,
)
from app.features.automation_center.providers.dagu_client import DaguClient
from app.features.automation_center.providers.status import map_external_status


class DaguProvider:
    """Translate Dagu DAG runs into platform execution records."""

    provider_type = "DAGU"

    def __init__(self, client: DaguClient):
        """保存 Dagu HTTP 客户端供统一运行契约调用。"""
        self._client = client

    @classmethod
    def from_config(cls, config: AutomationIntegrationConfig) -> "DaguProvider":
        """从服务端加密配置解密 API Key 并创建 Dagu 客户端。"""
        api_key = decrypt_secret(config.dagu_api_key_encrypted or "")
        if not api_key:
            raise ProviderError("Dagu API Key 未配置")
        return cls(DaguClient(
            config.dagu_base_url or "", api_key,
            allow_insecure_http=settings.DAGU_ALLOW_INSECURE_HTTP,
        ))

    def close(self) -> None:
        """释放底层 HTTP 连接池。"""
        self._client.close()

    def test_connection(self, resource_id: str | None = None) -> ProviderConnectionResult:
        """校验 OpenAPI、健康状态、版本和 DAG 读取权限。"""
        openapi = self._client.get_openapi()
        health = self._client.get_health()
        dags = self._client.list_dags()
        if resource_id:
            self._client.get_dag_spec(resource_id)
            return ProviderConnectionResult(True, "已连接 Dagu，DAG 可读取", 1, self._version(health, openapi))
        return ProviderConnectionResult(True, "已连接 Dagu", len(dags), self._version(health, openapi))

    def list_dags(self) -> list[dict]:
        """返回可读 DAG 列表，兼容文件名和 DAG 元数据分开封装的响应。"""
        return self._client.list_dags()

    def trigger_run(self, resource_id: str, params: dict[str, Any]) -> ProviderExecution:
        """过滤触发参数中的敏感字段并使用稳定运行 ID 入队。"""
        execution_id = str(params.get("execution_id") or "").strip()
        if not execution_id.isdigit():
            raise ProviderError("平台执行 ID 无效")
        dag_run_id = f"automation-{execution_id}"
        queue = str(params.get("queue") or "automation-tests")
        dag_params = {
            "execution_id": execution_id,
            "automation_project_id": str(params.get("automation_project_id") or ""),
            "integration_config_id": str(params.get("integration_config_id") or ""),
            "repository_url": str(params.get("repository_url") or ""),
            "repository_id": str(params.get("repository_id") or ""),
            "branch": str(params.get("branch") or ""),
            "environment_name": str(params.get("environment_name") or ""),
            "pytest_args": str(params.get("pytest_args") or ""),
            "test_tags": str(params.get("test_tags") or ""),
            "test_scope": str(params.get("test_scope") or ""),
            "timeout_seconds": str(params.get("timeout_seconds") or "3600"),
            "queue": queue,
        }
        try:
            response = self._client.enqueue(resource_id, dag_params, dag_run_id, queue)
        except ProviderError as exc:
            if exc.status_code != 409:
                raise
            # A retry after a lost enqueue response reuses the stable ID and returns that run.
            response = self._client.get_run(resource_id, dag_run_id)
            response["dagRunId"] = response.get("dagRunId") or dag_run_id
        actual_run_id = str(response.get("dagRunId") or response.get("dag_run_id") or dag_run_id)
        return ProviderExecution(
            provider_type=self.provider_type,
            external_run_id=actual_run_id,
            status="PENDING",
            external_status="queued",
            raw=response,
        )

    def get_run(self, resource_id: str, external_run_id: str | None = None) -> ProviderExecution:
        """按 Dagu DAG 名和运行 ID 读取统一运行状态。"""
        if not external_run_id:
            raise ProviderError("查询 Dagu 运行需要 dagRunId")
        return self._from_payload(self._client.get_run(resource_id, external_run_id), external_run_id)

    def stop_run(
        self,
        resource_id: str,
        external_run_id: str | None = None,
    ) -> bool:
        """读取当前状态后执行 dequeue 或 stop，避免对终态重复发送停止。"""
        if not external_run_id:
            return False
        run = self._client.get_run(resource_id, external_run_id)
        label = str(run.get("statusLabel") or "").lower()
        if label == "queued":
            self._client.dequeue(resource_id, external_run_id)
        elif label == "running":
            self._client.stop(resource_id, external_run_id)
        elif label not in {"succeeded", "failed", "partially_succeeded", "rejected", "aborted"}:
            return False
        return True

    def get_log(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        *,
        max_bytes: int = 200_000,
    ) -> str | None:
        """读取并限幅 Dagu Run 日志。"""
        if not external_run_id:
            return None
        return self._client.get_log(resource_id, external_run_id, tail=2000, limit=max_bytes)

    def list_runs(self, resource_id: str, *, per_page: int = 10) -> list[ProviderExecution]:
        """列出指定 DAG 的最近运行并映射为平台通用执行对象。"""
        return [self._from_payload(item) for item in self._client.list_runs(resource_id, limit=per_page)]

    @classmethod
    def _from_payload(cls, payload: dict[str, Any], run_id: str | None = None) -> ProviderExecution:
        """将 Dagu 的运行详情字段归一化为平台执行状态和时间戳。"""
        raw_status = str(payload.get("statusLabel") or "")
        actual_id = payload.get("dagRunId") or payload.get("dag_run_id") or payload.get("runId") or run_id
        started = cls._timestamp(payload.get("startedAt"))
        finished = cls._timestamp(payload.get("finishedAt"))
        duration = int((finished - started).total_seconds() * 1000) if started and finished else None
        error_message = payload.get("error")
        if isinstance(error_message, str):
            error_message = error_message[:500]
        return ProviderExecution(
            provider_type=cls.provider_type,
            external_run_id=str(actual_id) if actual_id is not None else None,
            status=map_external_status(payload),
            external_status=raw_status[:40],
            started_at=started,
            finished_at=finished,
            duration_ms=duration,
            error_message=error_message or None,
            raw=payload,
        )

    @staticmethod
    def _version(health: dict[str, Any], openapi: dict[str, Any]) -> str | None:
        """优先返回 Dagu Health 的服务版本，缺失时回退到 OpenAPI 版本。"""
        info = openapi.get("info")
        value = health.get("version") or (info.get("version") if isinstance(info, dict) else None)
        return str(value)[:80] if value else None

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        """解析 Dagu 的毫秒时间戳或 RFC3339 时间字符串。"""
        if not value:
            return None
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                return None
        return None
