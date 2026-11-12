"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.business.schemas.common import BusinessVariableDataType
from app.features.business.schemas.common import BusinessVariableDirection


class BusinessVariableBase(BaseModel):
    """业务变量共有字段。"""

    direction: BusinessVariableDirection = Field(..., description="方向：INPUT/OUTPUT")
    name: str = Field(..., min_length=1, max_length=100, description="变量名，如 project_id/task_id")
    data_type: BusinessVariableDataType = Field(
        default="STRING", description="数据类型：STRING/INTEGER/NUMBER/BOOLEAN/OBJECT/ARRAY",
    )
    required: bool = Field(default=False, description="是否必填")
    description: str | None = Field(None, max_length=500, description="变量说明")
    sort: int = Field(default=0, ge=0, description="排序值")


class BusinessVariableCreate(BusinessVariableBase):
    """新增业务变量入参（action_id 由路径提供）。"""


class BusinessVariableUpdate(BaseModel):
    """修改业务变量入参（局部）。"""

    direction: BusinessVariableDirection | None = None
    name: str | None = Field(None, min_length=1, max_length=100)
    data_type: BusinessVariableDataType | None = None
    required: bool | None = None
    description: str | None = Field(None, max_length=500)
    sort: int | None = Field(None, ge=0)


class BusinessVariableResponse(BaseModel):
    """业务变量响应。"""

    id: int
    action_id: int
    direction: str
    name: str
    data_type: str
    required: bool
    description: str | None = None
    sort: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
