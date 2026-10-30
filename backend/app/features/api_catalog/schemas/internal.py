"""api_catalog 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field, field_validator
from app.features.api_catalog.schemas.common import ApiSourceType
from app.features.api_catalog.schemas.common import BodyType
from app.features.api_catalog.schemas.common import ParamLocation


class InternalParameter(BaseModel):
    """内部参数模型：所有 parser 输出、服务层消费的参数表示。"""

    name: str
    location: ParamLocation
    type: str = "string"
    required: bool = False
    description: str | None = None
    example: str | None = None
    default_value: str | None = None
    schema_json: dict[str, Any] | None = None
    sort: int = 0


class InternalBody(BaseModel):
    """内部请求体模型。"""

    body_type: BodyType = "none"
    content_type: str | None = None
    schema_json: dict[str, Any] | None = None
    raw_text: str | None = None


class InternalResponse(BaseModel):
    """内部响应模型。"""

    status_code: int
    description: str | None = None
    schema_json: dict[str, Any] | None = None
    example_json: str | None = None
    sort: int = 0


class InternalApiSchema(BaseModel):
    """统一 Internal API Schema：所有外部格式先转成它，后续 Agent 只依赖它。

    不依赖 curl/openapi 原始格式；source_hash 由 import_service 用 compute_source_hash 计算。
    """

    name: str
    description: str | None = None
    method: str
    path: str
    auth_type: str = "none"
    content_type: str = "application/json"
    parameters: list[InternalParameter] = Field(default_factory=list)
    body: InternalBody = Field(default_factory=InternalBody)
    responses: list[InternalResponse] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    suggested_module: str | None = None
    source_type: ApiSourceType = "MANUAL"
    source_hash: str | None = None

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, v: Any) -> str:
        """HTTP 方法统一大写。"""
        return str(v or "").upper()

    @field_validator("path", mode="before")
    @classmethod
    def normalize_path(cls, v: Any) -> str:
        """路径统一以 / 开头，且不重复斜杠。"""
        p = str(v or "").strip()
        if not p:
            return "/"
        if not p.startswith("/"):
            p = "/" + p
        # 合并多余斜杠（保留协议双斜杠被 urlsplit 处理，这里只处理路径段）
        while "//" in p:
            p = p.replace("//", "/")
        return p
