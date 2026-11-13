"""自动化中心 CI Provider 的统一契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class ProviderError(Exception):
    """Provider 调用失败；message 必须已经去除认证信息。"""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ProviderExecution:
    """各 CI 平台映射后的统一运行结果。"""

    provider_type: str
    external_run_id: str | None = None
    queue_id: str | None = None
    build_number: int | None = None
    build_url: str | None = None
    status: str = "PENDING"
    external_status: str = ""
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    trigger_source: str = "EXTERNAL"
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


@dataclass(frozen=True)
class ProviderConnectionResult:
    """连接测试的统一结果。"""

    ok: bool
    message: str
    sample_run_count: int = 0


class AutomationProvider(Protocol):
    """Provider 层执行接口。"""

    provider_type: str

    def test_connection(self, resource_id: str | None = None) -> ProviderConnectionResult: ...

    def trigger_build(self, resource_id: str, params: dict[str, Any]) -> ProviderExecution: ...

    def get_queue_item(self, queue_id: str) -> ProviderExecution | None: ...

    def get_build(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        build_number: int | None = None,
    ) -> ProviderExecution: ...

    def stop_build(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        *,
        queue_id: str | None = None,
        build_number: int | None = None,
    ) -> bool: ...

    def get_console_log(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        build_number: int | None = None,
        *,
        max_bytes: int = 200_000,
    ) -> str | None: ...

    def get_build_url(
        self,
        resource_id: str,
        external_run_id: str | None = None,
        build_number: int | None = None,
    ) -> str | None: ...

    def list_runs(self, resource_id: str, *, per_page: int = 10) -> list[ProviderExecution]: ...
