"""api_catalog 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModuleCreate(BaseModel):
    """新建模块。"""

    name: str = Field(..., min_length=1, max_length=100)
    parent_id: int | None = Field(default=None, gt=0)
    sort: int = 0

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: Any) -> str:
        """清理名称。"""
        return str(v or "").strip()


class ApiModuleUpdate(BaseModel):
    """更新模块（改名/排序）。未分类不可改名。"""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    sort: int | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: Any) -> Any:
        """清理名称。"""
        return str(v).strip() if v is not None else None


class ApiModuleMove(BaseModel):
    """移动模块（改 parent_id，校验两级与无环）。"""

    parent_id: int | None = Field(default=None, gt=0)


class ApiModuleResponse(BaseModel):
    """模块响应。"""

    id: int
    project_id: int
    name: str
    parent_id: int | None = None
    sort: int = 0
    is_default: bool = False
    interface_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
