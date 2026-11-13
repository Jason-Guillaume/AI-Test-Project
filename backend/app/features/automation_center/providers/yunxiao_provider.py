"""云效 Flow 的统一 Provider 适配器。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.security.crypto import decrypt_secret
from app.features.automation_center.models.entities import AutomationIntegrationConfig
from app.features.automation_center.providers.base import (
    ProviderConnectionResult,
    ProviderError,
    ProviderExecution,
)
from app.features.automation_center.providers.status import map_external_status
from app.features.automation_center.providers.yunxiao_client import YunxiaoClient, YunxiaoError

_TRIGGER_SOURCE = {
    "1": "EXTERNAL",
    "2": "SCHEDULE",
    "3": "CODE_PUSH",
    "5": "EXTERNAL",
    "6": "WEBHOOK",
}


class YunxiaoProvider:
    """把云效 OpenAPI 映射为统一执行契约，保留现有 API 调用方式。"""

    provider_type = "YUNXIAO"

    def __init__(self, client: YunxiaoClient):
        self._client = client

    @classmethod
    def from_config(cls, config: AutomationIntegrationConfig) -> "YunxiaoProvider":
        """由接入配置创建客户端；令牌只在 Provider 内解密。"""
        client = YunxiaoClient(
            base_url=config.api_base_url,
            token=decrypt_secret(config.access_token_encrypted),
            organization_id=config.organization_id,
            deployment=config.deployment,
        )
        return cls(client)

    def test_connection(self, resource_id: str | None = None) -> ProviderConnectionResult:
        if not resource_id:
            raise ProviderError("测试云效连接需要流水线 ID")
        runs = self._call(self._client.list_runs, resource_id, per_page=1)
        return ProviderConnectionResult(ok=True, message="已连接云效流水线", sample_run_count=len(runs))

    def trigger_build(self, resource_id: str, params: dict[str, Any]) -> ProviderExecution:
        run_id = self._call(self._client.create_run, resource_id, self._yunxiao_params(params))
        return ProviderExecution(
            provider_type=self.provider_type,
            external_run_id=run_id,
            status="RUNNING",
            external_status="RUNNING",
        )

    def get_queue_item(self, queue_id: str) -> ProviderExecution | None:
        # 云效在触发响应中直接返回运行实例 ID，没有独立队列资源。
        return None

    def get_build(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        build_number: int | None = None,
    ) -> ProviderExecution:
        if not external_run_id:
            raise ProviderError("查询云效运行需要运行实例 ID")
        payload = self._call(self._client.get_run, resource_id, external_run_id)
        return self._from_payload(payload, external_run_id=external_run_id)

    def stop_build(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        *,
        queue_id: str | None = None,
        build_number: int | None = None,
    ) -> bool:
        if not external_run_id:
            return False
        return self._call(self._client.stop_run, resource_id, external_run_id)

    def get_console_log(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        build_number: int | None = None,
        *,
        max_bytes: int = 200_000,
    ) -> str | None:
        # 现有云效客户端没有 Console Output 接口；执行回调日志仍由共享回调保存。
        return None

    def get_build_url(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        build_number: int | None = None,
    ) -> str | None:
        if not external_run_id:
            return None
        return self.get_build(resource_id, external_run_id).build_url

    def list_runs(self, resource_id: str, *, per_page: int = 10) -> list[ProviderExecution]:
        payloads = self._call(self._client.list_runs, resource_id, per_page=per_page)
        return [
            self._from_payload(payload)
            for payload in payloads
            if payload.get("pipelineRunId") is not None or payload.get("id") is not None
        ]

    @staticmethod
    def _call(method, *args, **kwargs):
        try:
            return method(*args, **kwargs)
        except YunxiaoError as exc:
            raise ProviderError(str(exc), exc.status_code) from exc

    @classmethod
    def _from_payload(
        cls, payload: dict[str, Any], *, external_run_id: str | None = None,
    ) -> ProviderExecution:
        raw_status = str(payload.get("status") or "")
        run_id = payload.get("pipelineRunId") or payload.get("id") or external_run_id
        start = cls._timestamp(payload.get("startTime"))
        finish = cls._timestamp(payload.get("finishTime") or payload.get("endTime"))
        duration = payload.get("durationMs")
        try:
            duration_ms = int(duration) if duration is not None else (
                int((finish - start).total_seconds() * 1000) if start and finish else None
            )
        except (TypeError, ValueError):
            duration_ms = None
        url = payload.get("pipelineRunUrl") or payload.get("webUrl") or payload.get("url")
        return ProviderExecution(
            provider_type=cls.provider_type,
            external_run_id=str(run_id) if run_id is not None else None,
            build_url=str(url) if url else None,
            status=map_external_status(payload),
            external_status=(raw_status or map_external_status(payload))[:40],
            started_at=start,
            finished_at=finish,
            duration_ms=duration_ms,
            trigger_source=_TRIGGER_SOURCE.get(str(payload.get("triggerMode")), "EXTERNAL"),
            raw=payload,
        )

    @staticmethod
    def _yunxiao_params(params: dict[str, Any]) -> dict[str, Any]:
        """把平台通用参数转成云效 Flow 的现有报文。"""
        envs = {
            "TEST_ENV": params.get("environment_name", ""),
            "PYTEST_ARGS": params.get("pytest_args", ""),
            "TEST_TAGS": params.get("test_tags", ""),
            "TEST_SCOPE": params.get("test_scope", ""),
            "AUTOMATION_EXECUTION_ID": params.get("execution_id", ""),
            "AUTOMATION_PROJECT_ID": params.get("automation_project_id", ""),
            "AUTOMATION_CALLBACK_KEY": params.get("callback_key", ""),
        }
        if params.get("callback_url"):
            envs["AUTOMATION_CALLBACK_URL"] = params["callback_url"]
        if params.get("history_url"):
            envs["AUTOMATION_HISTORY_URL"] = params["history_url"]
        variables = params.get("variables")
        if isinstance(variables, dict):
            envs.update(variables)
        envs = {key: value for key, value in envs.items() if value}
        request: dict[str, Any] = {
            "envs": envs,
            "comment": f"测试平台执行 {params.get('execution_id', '')}",
        }
        branch = params.get("branch")
        if branch:
            request["branchModeBranchs"] = [branch]
            if params.get("repository_url"):
                request["runningBranchs"] = {params["repository_url"]: branch}
        return request

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        try:
            milliseconds = int(value)
        except (TypeError, ValueError):
            return None
        if milliseconds <= 0:
            return None
        return datetime.fromtimestamp(milliseconds / 1000)
