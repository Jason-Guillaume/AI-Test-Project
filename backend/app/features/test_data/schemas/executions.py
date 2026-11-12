"""test_data 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ProviderExecutionResponse(BaseModel):
    """input_snapshot / output_snapshot 已脱敏；`_cleanup` 保留键不进入契约输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    fixture_execution_id: int | None = None
    data_execution_id: int | None = None
    project_id: int
    provider_id: int | None = None
    provider_type: str
    step_id: int | None = None
    status: str
    input_snapshot: dict[str, Any] | None = None
    output_snapshot: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    cleanup_status: str | None = None


class FixtureExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    data_execution_id: int
    project_id: int
    fixture_id: int | None = None
    fixture_key: str
    status: str
    scope: str
    cache_hit: bool
    input_snapshot: dict[str, Any] | None = None
    output_snapshot: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    cleanup_status: str | None = None
    cleanup_error_code: str | None = None
    cleanup_error_message: str | None = None
    provider_executions: list[ProviderExecutionResponse] = Field(default_factory=list)


class DataExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    test_run_id: int | None = None
    case_execution_id: int | None = None
    environment_id: int | None = None
    status: str
    scope: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    cleanup_status: str | None = None
    cleanup_error_code: str | None = None
    cleanup_error_message: str | None = None
    fixture_key_count: int = 0
    provider_step_count: int = 0
    created_at: datetime


class DataExecutionDetailResponse(DataExecutionResponse):
    """详情：总记录 + Fixture 执行链 + 每步 Provider 执行的 input/output/error。

    ``provider_executions`` 是**没有归属 Fixture** 的步骤记录——手工试跑单个
    Provider 时 ``fixture_execution_id`` 为空，只能挂在这一层。
    """

    fixture_executions: list[FixtureExecutionResponse] = Field(default_factory=list)
    provider_executions: list[ProviderExecutionResponse] = Field(default_factory=list)


class DataExecutionListResponse(BaseModel):
    items: list[DataExecutionResponse]
    page: int
    page_size: int
    total: int
