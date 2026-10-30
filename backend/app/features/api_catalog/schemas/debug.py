"""api_catalog 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class ApiDebugRequest(BaseModel):
    """调试请求（仅平台管理员）。"""

    environment_name: str = Field(..., min_length=1, max_length=50)
    override_headers: dict[str, str] | None = None
    override_path_params: dict[str, str] | None = None
    override_query: dict[str, str] | None = None
    override_body: Any | None = None
    timeout: float = Field(default=30.0, ge=1.0, le=120.0)


class ApiDebugResponse(BaseModel):
    """调试响应。仅临时请求，不生成用例、不落库。"""

    status_code: int
    response_body: str
    response_headers: dict[str, str] = Field(default_factory=dict)
    response_time_ms: int
    request_url: str
    outbound_target_id: int | None = None
