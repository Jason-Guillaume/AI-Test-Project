"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class BusinessVariableRefCreate(BaseModel):
    """新增变量引用入参（flow_id 由路径提供）。"""

    source_action_id: int = Field(..., gt=0, description="来源动作ID（输出方）")
    source_variable: str = Field(..., min_length=1, max_length=100, description="来源动作输出变量名")
    source_variable_id: int | None = Field(None, gt=0, description="来源变量ID（FK → business_variable）")
    target_action_id: int = Field(..., gt=0, description="目标动作ID（输入方）")
    target_variable: str = Field(..., min_length=1, max_length=100, description="目标动作输入变量名")
    target_variable_id: int | None = Field(None, gt=0, description="目标变量ID（FK → business_variable）")


class BusinessVariableRefResponse(BaseModel):
    """业务变量引用响应。"""

    id: int
    flow_id: int
    source_action_id: int
    source_variable: str
    source_variable_id: int | None = None
    target_action_id: int
    target_variable: str
    target_variable_id: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
