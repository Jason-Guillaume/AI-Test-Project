"""test_data 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field
from app.features.test_data.schemas.common import MappingLocation


class MappingRule(BaseModel):
    """输入映射：把表达式求值结果写到目标字段的指定位置。"""

    target: str = Field(..., min_length=1, max_length=200, description="目标字段名")
    location: MappingLocation = Field(default="BODY", description="写入位置")
    expression: str = Field(..., min_length=1, max_length=500, description="模板表达式，如 ${faker.name}")


class OutputMapping(BaseModel):
    """输出映射：从响应体按 JSONPath 提取变量。"""

    name: str = Field(..., min_length=1, max_length=100, description="变量名")
    expression: str = Field(..., min_length=1, max_length=300, description="JSONPath，如 $.data.id")


class CleanupBinding(BaseModel):
    """API 类 Provider 的清理绑定：只存 method + path 模板，执行时再次过出站白名单。"""

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = Field(default="DELETE")
    path: str = Field(..., min_length=1, max_length=500, description="路径模板，可含 ${fixture.X.y}")
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)
