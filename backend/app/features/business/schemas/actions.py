"""business 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.features.business.schemas.common import BusinessActionType
from app.features.business.schemas.bindings import BusinessBindingDetailResponse
from app.features.business.schemas.preconditions import BusinessPreconditionResponse
from app.features.business.schemas.states import BusinessStateResponse
from app.features.business.schemas.variables import BusinessVariableResponse


class BusinessActionBase(BaseModel):
    """业务动作共有字段。"""

    name: str = Field(..., min_length=1, max_length=200, description="动作名称")
    description: str | None = Field(None, max_length=1000, description="动作描述")
    action_key: str = Field(
        ..., min_length=1, max_length=100,
        description="稳定业务标识，如 LOGIN/CREATE_TASK，不依赖接口ID",
    )
    sort: int = Field(default=0, ge=0, description="步骤顺序，越小越靠前")
    action_type: BusinessActionType = Field(
        default="NORMAL", description="当前仅支持普通顺序动作 NORMAL",
    )


class BusinessActionCreate(BusinessActionBase):
    """新增业务动作入参（flow_id 由路径提供）。"""


class BusinessActionUpdate(BaseModel):
    """修改业务动作入参（局部）。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    action_key: str | None = Field(None, min_length=1, max_length=100)
    sort: int | None = Field(None, ge=0)
    action_type: BusinessActionType | None = None
    revision: int | None = Field(None, ge=1, description="乐观锁版本号")


class BusinessActionResponse(BaseModel):
    """业务动作响应（基本信息）。"""

    id: int
    flow_id: int
    name: str
    description: str | None = None
    action_key: str
    sort: int
    action_type: str
    revision: int = 1
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessActionReorderItem(BaseModel):
    """排序项：动作ID + 新顺序值。"""

    action_id: int = Field(..., gt=0)
    sort: int = Field(..., ge=0)


class BusinessActionReorder(BaseModel):
    """批量重排业务动作入参。"""

    items: list[BusinessActionReorderItem] = Field(..., min_length=1)


class BusinessActionDetailResponse(BusinessActionResponse):
    """业务动作详情：基本信息 + 前置条件 + 输入/输出变量 + 状态 + 绑定详情。"""

    preconditions: list[BusinessPreconditionResponse] = Field(default_factory=list)
    input_variables: list[BusinessVariableResponse] = Field(default_factory=list)
    output_variables: list[BusinessVariableResponse] = Field(default_factory=list)
    states: list[BusinessStateResponse] = Field(default_factory=list)
    binding: BusinessBindingDetailResponse | None = Field(
        None, description="该动作的绑定详情；无绑定时为 None",
    )
