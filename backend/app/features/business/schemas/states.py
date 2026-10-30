"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class BusinessStateCreate(BaseModel):
    """新增业务状态入参（action_id 由路径提供；每个动作对一个实体最多一组 Pre/Post）。"""

    entity: str = Field(..., min_length=1, max_length=100, description="状态所属实体，如 task/project")
    pre_state: str | None = Field(None, max_length=50, description="前置状态，如 CREATED")
    post_state: str | None = Field(None, max_length=50, description="后置状态，如 RUNNING")


class BusinessStateUpdate(BaseModel):
    """修改业务状态入参（局部）。"""

    entity: str | None = Field(None, min_length=1, max_length=100)
    pre_state: str | None = Field(None, max_length=50)
    post_state: str | None = Field(None, max_length=50)


class BusinessStateResponse(BaseModel):
    """业务状态响应。"""

    id: int
    action_id: int
    entity: str
    pre_state: str | None = None
    post_state: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
