"""api_catalog 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.features.api_catalog.schemas.common import BodyType
from app.features.api_catalog.schemas.common import ParamLocation
from app.features.api_catalog.schemas.response_keys import normalize_response_key


class ApiParameterIn(BaseModel):
    """请求参数写入字段。"""

    name: str
    location: ParamLocation
    type: str = "string"
    required: bool = False
    description: str | None = None
    example: str | None = None
    default_value: str | None = None
    schema_json: dict[str, Any] | None = None
    sort: int = 0


class ApiBodyIn(BaseModel):
    """请求体写入字段。"""

    body_type: BodyType = "none"
    content_type: str | None = None
    schema_json: dict[str, Any] | None = None
    raw_text: str | None = None


class ApiResponseIn(BaseModel):
    """响应写入字段。"""

    status_code: int | None = Field(default=None, ge=100, le=599)
    response_key: str
    description: str | None = None
    schema_json: dict[str, Any] | None = None
    example_json: str | None = None
    sort: int = 0

    @model_validator(mode="before")
    @classmethod
    def normalize_key(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        key = data.get("response_key")
        code = data.get("status_code")
        if key is None and code is not None:
            key = str(code)
        if key is None:
            raise ValueError("响应定义必须包含 response_key 或 status_code")
        normalized, parsed_code = normalize_response_key(key)
        if code is not None and parsed_code != int(code):
            raise ValueError("response_key 与 status_code 不一致")
        data["response_key"] = normalized
        data["status_code"] = parsed_code
        return data


class ApiParameterResponse(BaseModel):
    """参数响应。"""

    id: int
    interface_id: int
    name: str
    location: ParamLocation
    type: str
    required: bool
    description: str | None = None
    example: str | None = None
    default_value: str | None = None
    schema_json: dict[str, Any] | None = None
    sort: int = 0

    model_config = ConfigDict(from_attributes=True)


class ApiRequestBodyResponse(BaseModel):
    """请求体响应。"""

    id: int | None = None
    interface_id: int
    body_type: BodyType = "none"
    content_type: str | None = None
    schema_json: dict[str, Any] | None = None
    raw_text: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ApiResponseResponse(BaseModel):
    """响应项响应。"""

    id: int
    interface_id: int
    status_code: int | None = None
    response_key: str
    description: str | None = None
    schema_json: dict[str, Any] | None = None
    example_json: str | None = None
    sort: int = 0

    model_config = ConfigDict(from_attributes=True)


class ApiRequestBundle(BaseModel):
    """请求参数+body 整体替换载荷（PUT /interfaces/{id}/request）。"""

    parameters: list[ApiParameterIn] = Field(default_factory=list)
    body: ApiBodyIn = Field(default_factory=ApiBodyIn)


class ApiRequestBundleResponse(BaseModel):
    """请求参数+body 响应（GET /interfaces/{id}/request）。"""

    parameters: list[ApiParameterResponse] = Field(default_factory=list)
    body: ApiRequestBodyResponse | None = None


class ApiResponsesBundle(BaseModel):
    """响应整体替换载荷（PUT /interfaces/{id}/responses）。"""

    responses: list[ApiResponseIn] = Field(default_factory=list)


class ApiResponsesBundleResponse(BaseModel):
    """响应列表响应。"""

    responses: list[ApiResponseResponse] = Field(default_factory=list)
