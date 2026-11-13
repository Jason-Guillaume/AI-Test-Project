"""Jenkins adapter for the common automation execution contract."""

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
from app.features.automation_center.providers.jenkins_client import JenkinsClient


class JenkinsProvider:
    """Translate Jenkins Queue and Build API responses to platform statuses."""

    provider_type = "JENKINS"

    def __init__(self, client: JenkinsClient):
        self._client = client

    @classmethod
    def from_config(cls, config: AutomationIntegrationConfig) -> "JenkinsProvider":
        credential = config.jenkins_credential
        if credential is None:
            raise ProviderError("Jenkins 凭据未配置")
        token = decrypt_secret(credential.api_token_encrypted)
        if not token:
            raise ProviderError("Jenkins API Token 解密失败或未配置")
        client = JenkinsClient(
            credential.base_url,
            credential.username,
            token,
            timeout_seconds=15,
            allow_private_network=config.allow_private_network,
        )
        return cls(client)

    def test_connection(self, resource_id: str | None = None) -> ProviderConnectionResult:
        identity = self._client.test_connection()
        message = f"已连接 Jenkins（{identity.get('name', 'authenticated user')}）"
        count = 0
        if resource_id:
            job = self._client.get_item(resource_id)
            if "Folder" in str(job.get("_class", "")) or job.get("buildable") is False:
                raise ProviderError("Jenkins Job 不存在或不可执行")
            message = f"{message}，Job 可执行"
            count = 1
        return ProviderConnectionResult(ok=True, message=message, sample_run_count=count)

    def list_items(self, folder_path: str = "") -> list[dict[str, Any]]:
        """List one Jenkins root or folder level for the job picker."""
        parent = self._client.validate_job_path(folder_path) if folder_path.strip("/") else ""
        items = self._client.list_items(parent)
        result = []
        for item in items:
            name = str(item.get("name") or "")
            if not name:
                continue
            job_path = f"{parent}/{name}" if parent else name
            result.append({
                "name": name,
                "job_path": job_path,
                "url": str(item.get("url") or ""),
                "is_folder": "Folder" in str(item.get("_class", "")),
                "buildable": item.get("buildable") is not False,
                "color": str(item.get("color") or ""),
            })
        return result

    def inspect_job(self, job_path: str) -> dict[str, Any]:
        """Return a safe subset of Job parameters and execution capabilities."""
        payload = self._client.get_item(job_path)
        parameters = []
        for prop in payload.get("property", []) or []:
            for definition in prop.get("parameterDefinitions", []) or []:
                if isinstance(definition, dict) and definition.get("name"):
                    default = definition.get("defaultParameterValue") or {}
                    parameters.append({
                        "name": str(definition["name"]),
                        "type": str(definition.get("type") or ""),
                        "default_value": str(default.get("value") or "")[:500],
                    })
        return {
            "name": str(payload.get("name") or ""),
            "job_path": self._client.validate_job_path(job_path),
            "url": str(payload.get("url") or ""),
            "is_folder": "Folder" in str(payload.get("_class", "")),
            "buildable": payload.get("buildable") is not False,
            "concurrent_build": bool(payload.get("concurrentBuild")),
            "parameters": parameters,
        }

    def trigger_build(self, resource_id: str, params: dict[str, Any]) -> ProviderExecution:
        parameters = {
            "BRANCH_NAME": params.get("branch", ""),
            "TEST_ENV": params.get("environment_name", ""),
            "PYTEST_ARGS": params.get("pytest_args", ""),
            "TEST_TAGS": params.get("test_tags", ""),
            "TEST_SCOPE": params.get("test_scope", ""),
            "REPOSITORY_URL": params.get("repository_url", ""),
            "REPOSITORY_ID": params.get("repository_id", ""),
            "BUILD_TIMEOUT_MINUTES": str(min(max((int(params.get("timeout_seconds", 7200)) + 59) // 60, 1), 180)),
            "AUTOMATION_EXECUTION_ID": str(params.get("execution_id", "")),
            "AUTOMATION_PROJECT_ID": str(params.get("automation_project_id", "")),
            "AUTOMATION_CALLBACK_KEY": str(params.get("callback_key", "")),
            "AUTOMATION_CALLBACK_URL": str(params.get("callback_url", "")),
            "AUTOMATION_HISTORY_URL": str(params.get("history_url", "")),
            "AUTOMATION_PROVIDER": self.provider_type,
        }
        variables = params.get("variables")
        if isinstance(variables, dict):
            parameters.update(variables)
        safe = self._client.validate_parameters(parameters)
        queue_id = self._client.trigger_build(resource_id, safe)
        return ProviderExecution(
            provider_type=self.provider_type,
            queue_id=queue_id,
            external_run_id=f"queue:{queue_id}",
            status="PENDING",
            external_status="QUEUED",
        )

    def get_queue_item(self, queue_id: str) -> ProviderExecution | None:
        payload = self._client.get_queue_item(queue_id)
        if payload.get("cancelled"):
            return ProviderExecution(
                provider_type=self.provider_type,
                queue_id=str(queue_id),
                status="CANCELLED",
                external_status="CANCELLED",
                error_message=str(payload.get("why") or "Jenkins 队列任务已取消")[:500],
                raw=payload,
            )
        executable = payload.get("executable")
        if not isinstance(executable, dict) or executable.get("number") is None:
            return ProviderExecution(
                provider_type=self.provider_type,
                queue_id=str(queue_id),
                external_run_id=f"queue:{queue_id}",
                status="PENDING",
                external_status="QUEUED",
                error_message=str(payload.get("why") or "")[:500],
                raw=payload,
            )
        try:
            number = int(executable["number"])
        except (TypeError, ValueError) as exc:
            raise ProviderError("Jenkins Queue 返回了无效 Build Number") from exc
        return ProviderExecution(
            provider_type=self.provider_type,
            queue_id=str(queue_id),
            external_run_id=str(number),
            build_number=number,
            build_url=str(executable.get("url") or "") or None,
            status="RUNNING",
            external_status="BUILDING",
            started_at=datetime.now(),
            raw=payload,
        )

    def get_build(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        build_number: int | None = None,
    ) -> ProviderExecution:
        number = build_number
        if number is None and external_run_id and external_run_id.isdigit():
            number = int(external_run_id)
        if number is None:
            raise ProviderError("查询 Jenkins Build 需要 Build Number")
        payload = self._client.get_build(resource_id, number)
        is_building = bool(payload.get("building"))
        raw_status = str(payload.get("result") or ("BUILDING" if is_building else "UNKNOWN"))
        status = {
            "SUCCESS": "SUCCESS",
            "FAILURE": "FAILED",
            "ABORTED": "CANCELLED",
            "UNSTABLE": "FAILED",
        }.get(raw_status, "RUNNING" if is_building else "FAILED")
        timestamp = self._millis(payload.get("timestamp"))
        duration = self._integer(payload.get("duration"))
        finished = None if is_building else (timestamp if duration == 0 else None)
        if not is_building and timestamp and duration is not None:
            from datetime import timedelta

            finished = timestamp + timedelta(milliseconds=max(0, duration))
        commit = ""
        changes = payload.get("changeSet") or {}
        items = changes.get("items") or [] if isinstance(changes, dict) else []
        if items and isinstance(items[0], dict):
            commit = str(items[0].get("commitId") or "")[:64]
        return ProviderExecution(
            provider_type=self.provider_type,
            external_run_id=str(number),
            build_number=number,
            build_url=str(payload.get("url") or "") or None,
            status=status,
            external_status=raw_status[:40],
            started_at=timestamp,
            finished_at=finished,
            duration_ms=duration,
            error_message="Jenkins 构建状态未返回结果" if raw_status == "UNKNOWN" else None,
            raw={**payload, "git_commit": commit},
        )

    def stop_build(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        *,
        queue_id: str | None = None,
        build_number: int | None = None,
    ) -> bool:
        if queue_id and build_number is None and not (external_run_id and external_run_id.isdigit()):
            return self._client.cancel_queue_item(queue_id)
        number = build_number
        if number is None and external_run_id and external_run_id.isdigit():
            number = int(external_run_id)
        if number is None:
            return False
        return self._client.stop_build(resource_id, number)

    def get_console_log(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        build_number: int | None = None,
        *,
        max_bytes: int = 200_000,
    ) -> str | None:
        number = build_number
        if number is None and external_run_id and external_run_id.isdigit():
            number = int(external_run_id)
        if number is None:
            return None
        return self._client.get_console_log(resource_id, number, max_bytes=max_bytes)

    def get_build_url(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        build_number: int | None = None,
    ) -> str | None:
        number = build_number
        if number is None and external_run_id and external_run_id.isdigit():
            number = int(external_run_id)
        if number is None:
            return None
        return self._client.get_build(resource_id, number).get("url")

    def list_runs(self, resource_id: str, *, per_page: int = 10) -> list[ProviderExecution]:
        job = self._client.get_item(resource_id)
        builds = job.get("builds") or []
        result = []
        for item in builds[: min(max(per_page, 1), 50)]:
            if isinstance(item, dict) and item.get("number") is not None:
                result.append(self.get_build(resource_id, build_number=int(item["number"])))
        return result

    @staticmethod
    def _millis(value: Any) -> datetime | None:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(timestamp / 1000) if timestamp > 0 else None

    @staticmethod
    def _integer(value: Any) -> int | None:
        try:
            return max(0, int(value)) if value is not None else None
        except (TypeError, ValueError):
            return None
