"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class FlowExecutionRequest(BaseModel):
    """执行业务流程请求。"""

    environment_id: int = Field(..., gt=0, description="执行环境ID")
    variables: dict[str, Any] = Field(default_factory=dict, description="初始运行时变量")


class FlowExecutionResponse(BaseModel):
    """执行记录响应。"""

    id: int
    project_id: int
    flow_id: int
    environment_id: int | None = None
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    context_json: dict[str, Any] | None = None
    error_message: str | None = None
    error_code: str | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ActionExecutionResponse(BaseModel):
    """步骤执行记录响应。"""

    id: int
    flow_execution_id: int
    action_id: int | None = None
    binding_id: int | None = None
    sequence: int
    status: str
    request_snapshot: dict[str, Any] | None = None
    response_snapshot: dict[str, Any] | None = None
    input_context: dict[str, Any] | None = None
    output_context: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    error_code: str | None = None
    unverified_preconditions: list[dict[str, Any]] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FlowExecutionActionListResponse(BaseModel):
    """执行记录的步骤列表响应。"""

    items: list[ActionExecutionResponse]
    total: int
    page: int = 1
    page_size: int = 100
