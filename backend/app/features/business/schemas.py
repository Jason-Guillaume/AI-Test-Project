"""业务管理模块：契约定义（Pydantic v2）。

只放请求/响应模型与字面量类型，不含业务逻辑；service 与 router 共用本文件
作为两层接口契约（与 defects / api_catalog 的 schemas 风格一致）。

第一阶段 10 个实体 + 1 个聚合详情（BusinessFlowDetailResponse）。聚合详情把
流程下的动作、动作的前置条件/输入输出变量/状态/绑定/映射、流程的变量引用、规则
一次性组装返回，供前端「业务流程详情」右侧面板渲染，减少往返。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- 枚举字面量

# 各状态/类型字段在数据库层均为 String（不设 sa.Enum / CHECK），
# 合法取值由服务层校验；这里用 Literal 与常量元组双重声明，供路由/前端/文档复用。

BUSINESS_DOMAIN_STATUSES = ("ACTIVE", "INACTIVE")
BusinessDomainStatus = Literal["ACTIVE", "INACTIVE"]

BUSINESS_FLOW_STATUSES = ("DRAFT", "ACTIVE", "DEPRECATED")
BusinessFlowStatus = Literal["DRAFT", "ACTIVE", "DEPRECATED"]

# 当前执行器只实现普通顺序动作；历史动作类型仅通过响应字段读取，不再接受新配置。
BUSINESS_ACTION_TYPES = ("NORMAL",)
BusinessActionType = Literal["NORMAL"]

BUSINESS_BINDING_TYPES = ("API", "WEB")
BusinessBindingType = Literal["API", "WEB"]

BUSINESS_PRECONDITION_TYPES = ("VARIABLE", "STATE", "BUSINESS", "TEXT")
BusinessPreconditionType = Literal["VARIABLE", "STATE", "BUSINESS", "TEXT"]

BUSINESS_PRECONDITION_OPERATORS = ("EQ", "NE", "IN", "CONTAINS", "EXISTS", "NOT_EXISTS")
BusinessPreconditionOperator = Literal["EQ", "NE", "IN", "CONTAINS", "EXISTS", "NOT_EXISTS"]

BUSINESS_VARIABLE_DIRECTIONS = ("INPUT", "OUTPUT")
BusinessVariableDirection = Literal["INPUT", "OUTPUT"]

BUSINESS_VARIABLE_DATA_TYPES = (
    "STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY",
)
BusinessVariableDataType = Literal[
    "STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY"
]

BUSINESS_API_MAPPING_DIRECTIONS = ("INPUT", "OUTPUT")
BusinessApiMappingDirection = Literal["INPUT", "OUTPUT"]

BUSINESS_API_LOCATIONS = ("BODY", "HEADER", "QUERY", "PATH", "RESPONSE")
BusinessApiLocation = Literal["BODY", "HEADER", "QUERY", "PATH", "RESPONSE"]

BUSINESS_RULE_TYPES = ("GENERAL", "CONSTRAINT", "PRECONDITION")
BusinessRuleType = Literal["GENERAL", "CONSTRAINT", "PRECONDITION"]


# --------------------------------------------------------------------------- 业务域


class BusinessDomainBase(BaseModel):
    """业务域共有字段。"""

    name: str = Field(..., min_length=1, max_length=100, description="业务域名称")
    description: str | None = Field(None, max_length=500, description="业务域描述")
    sort: int = Field(default=0, ge=0, description="排序值，越小越靠前")
    status: BusinessDomainStatus = Field(default="ACTIVE", description="状态：ACTIVE/INACTIVE")


class BusinessDomainCreate(BusinessDomainBase):
    """新增业务域入参（project_id 由路径提供，不在此处重复）。"""


class BusinessDomainUpdate(BaseModel):
    """修改业务域入参（局部）。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = Field(None, max_length=500)
    sort: int | None = Field(None, ge=0)
    status: BusinessDomainStatus | None = None


class BusinessDomainResponse(BaseModel):
    """业务域响应。"""

    id: int
    project_id: int
    name: str
    description: str | None = None
    sort: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessDomainListResponse(BaseModel):
    """业务域列表响应。"""

    items: list[BusinessDomainResponse]
    total: int
    page: int = 1
    page_size: int = 20


# --------------------------------------------------------------------------- 业务流程


class BusinessFlowBase(BaseModel):
    """业务流程共有字段。"""

    name: str = Field(..., min_length=1, max_length=200, description="业务流程名称")
    description: str | None = Field(None, max_length=1000, description="业务流程描述")
    status: BusinessFlowStatus = Field(default="DRAFT", description="状态：DRAFT/ACTIVE/DEPRECATED")


class BusinessFlowCreate(BusinessFlowBase):
    """新增业务流程入参（project_id 由路径提供；domain_id 在请求体中）。"""

    domain_id: int = Field(..., gt=0, description="所属业务域ID")


class BusinessFlowUpdate(BaseModel):
    """修改业务流程入参（局部）。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    status: BusinessFlowStatus | None = None
    revision: int | None = Field(None, ge=1, description="乐观锁版本号（防并发冲突）")


class BusinessFlowResponse(BaseModel):
    """业务流程响应（基本信息）。"""

    id: int
    project_id: int
    domain_id: int
    name: str
    description: str | None = None
    status: str
    version: int
    revision: int = 1
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessFlowListResponse(BaseModel):
    """业务流程列表响应。"""

    items: list[BusinessFlowResponse]
    total: int
    page: int = 1
    page_size: int = 20


# --------------------------------------------------------------------------- 业务动作


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


# --------------------------------------------------------------------------- 业务动作：排序


class BusinessActionReorderItem(BaseModel):
    """排序项：动作ID + 新顺序值。"""

    action_id: int = Field(..., gt=0)
    sort: int = Field(..., ge=0)


class BusinessActionReorder(BaseModel):
    """批量重排业务动作入参。"""

    items: list[BusinessActionReorderItem] = Field(..., min_length=1)


# --------------------------------------------------------------------------- 业务前置条件


class BusinessPreconditionBase(BaseModel):
    """业务前置条件共有字段。"""

    type: BusinessPreconditionType = Field(..., description="前提类型：VARIABLE/STATE/BUSINESS/TEXT")
    target: str = Field(..., min_length=1, max_length=200, description="判断目标，如 task.status")
    operator: BusinessPreconditionOperator = Field(default="EQ", description="比较符：EQ/NE/IN/CONTAINS")
    expected_value: str | None = Field(None, max_length=500, description="期望值，多值用逗号分隔")
    description: str | None = Field(None, max_length=500, description="前提说明")
    sort: int = Field(default=0, ge=0, description="排序值")


class BusinessPreconditionCreate(BusinessPreconditionBase):
    """新增前置条件入参（action_id 由路径提供）。"""


class BusinessPreconditionUpdate(BaseModel):
    """修改前置条件入参（局部）。"""

    type: BusinessPreconditionType | None = None
    target: str | None = Field(None, min_length=1, max_length=200)
    operator: BusinessPreconditionOperator | None = None
    expected_value: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=500)
    sort: int | None = Field(None, ge=0)


class BusinessPreconditionResponse(BaseModel):
    """业务前置条件响应。"""

    id: int
    action_id: int
    type: str
    target: str
    operator: str
    expected_value: str | None = None
    description: str | None = None
    sort: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 业务变量


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


# --------------------------------------------------------------------------- 业务状态


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


# --------------------------------------------------------------------------- 业务变量引用


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


# --------------------------------------------------------------------------- 业务绑定


class BusinessBindingCreate(BaseModel):
    """新增业务绑定入参（action_id 由路径提供）。"""

    binding_type: BusinessBindingType = Field(default="API", description="绑定通道：API/WEB")
    api_id: int | None = Field(None, gt=0, description="绑定的接口ID（api_catalog.ApiInterface）")
    name: str | None = Field(None, max_length=200, description="绑定名称（如 API v1）")
    is_default: bool = Field(default=True, description="是否为默认绑定（执行时使用）")
    sort: int = Field(default=0, ge=0, description="绑定排序值")
    config_json: dict[str, Any] | None = Field(None, description="通道相关配置")
    enabled: bool = Field(default=True, description="是否启用该绑定")


class BusinessBindingUpdate(BaseModel):
    """修改业务绑定入参（局部）。"""

    binding_type: BusinessBindingType | None = None
    api_id: int | None = Field(None, gt=0)
    name: str | None = Field(None, max_length=200)
    is_default: bool | None = None
    sort: int | None = Field(None, ge=0)
    config_json: dict[str, Any] | None = None
    enabled: bool | None = None


class BusinessBindingResponse(BaseModel):
    """业务绑定响应（基本信息，不含失效判定与映射）。"""

    id: int
    action_id: int
    binding_type: str
    api_id: int | None = None
    name: str | None = None
    is_default: bool = True
    sort: int = 0
    config_json: dict[str, Any] | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 业务 API 接口 映射


class BusinessApiMappingCreate(BaseModel):
    """新增业务变量 ↔ 接口参数映射入参（binding_id 由路径提供）。"""

    direction: BusinessApiMappingDirection = Field(..., description="方向：INPUT/OUTPUT")
    business_variable: str = Field(..., min_length=1, max_length=100, description="业务变量名")
    api_location: BusinessApiLocation = Field(
        ..., description="接口位置：INPUT 用 BODY/HEADER/QUERY/PATH；OUTPUT 用 RESPONSE",
    )
    api_field: str | None = Field(None, max_length=300, description="接口字段路径，如 body.project_id")
    expression: str | None = Field(None, max_length=500, description="OUTPUT 时 JSONPath 表达式，如 $.data.id")


class BusinessApiMappingUpdate(BaseModel):
    """修改业务 API 映射入参（局部）。"""

    direction: BusinessApiMappingDirection | None = None
    business_variable: str | None = Field(None, min_length=1, max_length=100)
    api_location: BusinessApiLocation | None = None
    api_field: str | None = Field(None, max_length=300)
    expression: str | None = Field(None, max_length=500)


class BusinessApiMappingResponse(BaseModel):
    """业务 API 映射响应。"""

    id: int
    binding_id: int
    direction: str
    business_variable: str
    api_location: str
    api_field: str | None = None
    expression: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- 业务规则


class BusinessRuleBase(BaseModel):
    """业务规则共有字段。"""

    name: str = Field(..., min_length=1, max_length=200, description="规则名称")
    description: str | None = Field(None, max_length=1000, description="规则描述")
    rule_type: BusinessRuleType = Field(default="GENERAL", description="规则类型：GENERAL/CONSTRAINT/PRECONDITION")
    expression: str | None = Field(None, description="规则表达式（第一阶段仅人工维护，不自动执行）")
    enabled: bool = Field(default=True, description="是否启用")


class BusinessRuleCreate(BusinessRuleBase):
    """新增业务规则入参（project_id 由路径提供；flow_id/action_id 可选，为空表示项目级规则）。"""

    flow_id: int | None = Field(None, gt=0, description="所属业务流程ID；为空表示项目级规则")
    action_id: int | None = Field(None, gt=0, description="所属业务动作ID；为空表示流程/项目级规则")


class BusinessRuleUpdate(BaseModel):
    """修改业务规则入参（局部）。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    rule_type: BusinessRuleType | None = None
    expression: str | None = None
    enabled: bool | None = None


class BusinessRuleResponse(BaseModel):
    """业务规则响应。"""

    id: int
    project_id: int
    flow_id: int | None = None
    action_id: int | None = None
    name: str
    description: str | None = None
    rule_type: str
    expression: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BusinessRuleListResponse(BaseModel):
    """业务规则列表响应。"""

    items: list[BusinessRuleResponse]
    total: int
    page: int = 1
    page_size: int = 20


# --------------------------------------------------------------------------- 聚合详情

# 绑定详情：在基本信息之上叠加「失效判定」与「输入/输出映射」，供前端一站式渲染。
# valid=False 时 invalid_reason 给出原因（接口已删除 / 已废弃），满足「失效可见」要求。


class BusinessBindingDetailResponse(BusinessBindingResponse):
    """业务绑定详情：基本信息 + 失效判定 + 输入/输出映射。"""

    valid: bool = Field(..., description="绑定是否有效（接口存在且未废弃）")
    invalid_reason: str | None = Field(None, description="失效原因；valid=True 时为 None")
    api_name: str | None = Field(None, description="绑定接口名称（失效时为 None）")
    api_method: str | None = Field(None, description="绑定接口 HTTP 方法")
    api_path: str | None = Field(None, description="绑定接口路径")
    api_status: str | None = Field(None, description="绑定接口状态")
    input_mappings: list[BusinessApiMappingResponse] = Field(default_factory=list)
    output_mappings: list[BusinessApiMappingResponse] = Field(default_factory=list)


class BusinessActionDetailResponse(BusinessActionResponse):
    """业务动作详情：基本信息 + 前置条件 + 输入/输出变量 + 状态 + 绑定详情。"""

    preconditions: list[BusinessPreconditionResponse] = Field(default_factory=list)
    input_variables: list[BusinessVariableResponse] = Field(default_factory=list)
    output_variables: list[BusinessVariableResponse] = Field(default_factory=list)
    states: list[BusinessStateResponse] = Field(default_factory=list)
    binding: BusinessBindingDetailResponse | None = Field(
        None, description="该动作的绑定详情；无绑定时为 None",
    )


class BusinessFlowDetailResponse(BusinessFlowResponse):
    """业务流程聚合详情：流程 + 所属域 + 有序动作（含各自子配置）+ 变量引用 + 规则。

    前端「业务流程详情」右侧面板一次性拉取该结构，4 个 Tab 共享同一份数据，
    避免切 Tab 时各自再请求。动作按 sort 升序返回。
    """

    domain_name: str | None = Field(None, description="所属业务域名称")
    actions: list[BusinessActionDetailResponse] = Field(default_factory=list)
    variable_refs: list[BusinessVariableRefResponse] = Field(default_factory=list)
    rules: list[BusinessRuleResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------- 执行引擎

FLOW_EXECUTION_STATUSES = ("PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED")
FlowExecutionStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED"]

ACTION_EXECUTION_STATUSES = ("PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED")
ActionExecutionStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED"]


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


__all__ = [
    # 枚举常量
    "BUSINESS_ACTION_TYPES",
    "BUSINESS_API_LOCATIONS",
    "BUSINESS_API_MAPPING_DIRECTIONS",
    "BUSINESS_BINDING_TYPES",
    "BUSINESS_DOMAIN_STATUSES",
    "BUSINESS_FLOW_STATUSES",
    "BUSINESS_PRECONDITION_OPERATORS",
    "BUSINESS_PRECONDITION_TYPES",
    "BUSINESS_RULE_TYPES",
    "BUSINESS_VARIABLE_DATA_TYPES",
    "BUSINESS_VARIABLE_DIRECTIONS",
    "FLOW_EXECUTION_STATUSES",
    "ACTION_EXECUTION_STATUSES",
    # 业务域
    "BusinessDomainBase",
    "BusinessDomainCreate",
    "BusinessDomainListResponse",
    "BusinessDomainResponse",
    "BusinessDomainUpdate",
    # 业务流程
    "BusinessFlowBase",
    "BusinessFlowCreate",
    "BusinessFlowDetailResponse",
    "BusinessFlowListResponse",
    "BusinessFlowResponse",
    "BusinessFlowUpdate",
    # 业务动作
    "BusinessActionBase",
    "BusinessActionCreate",
    "BusinessActionDetailResponse",
    "BusinessActionReorder",
    "BusinessActionReorderItem",
    "BusinessActionResponse",
    "BusinessActionUpdate",
    # 前置条件
    "BusinessPreconditionBase",
    "BusinessPreconditionCreate",
    "BusinessPreconditionResponse",
    "BusinessPreconditionUpdate",
    # 变量
    "BusinessVariableBase",
    "BusinessVariableCreate",
    "BusinessVariableResponse",
    "BusinessVariableUpdate",
    # 状态
    "BusinessStateCreate",
    "BusinessStateResponse",
    "BusinessStateUpdate",
    # 变量引用
    "BusinessVariableRefCreate",
    "BusinessVariableRefResponse",
    # 绑定
    "BusinessBindingCreate",
    "BusinessBindingDetailResponse",
    "BusinessBindingResponse",
    "BusinessBindingUpdate",
    # API 映射
    "BusinessApiMappingCreate",
    "BusinessApiMappingResponse",
    "BusinessApiMappingUpdate",
    # 规则
    "BusinessRuleBase",
    "BusinessRuleCreate",
    "BusinessRuleListResponse",
    "BusinessRuleResponse",
    "BusinessRuleUpdate",
    # 执行引擎
    "FlowExecutionRequest",
    "FlowExecutionResponse",
    "FlowExecutionStatus",
    "ActionExecutionResponse",
    "ActionExecutionStatus",
    "FlowExecutionActionListResponse",
    # Literal 类型
    "BusinessActionType",
    "BusinessApiLocation",
    "BusinessApiMappingDirection",
    "BusinessBindingType",
    "BusinessDomainStatus",
    "BusinessFlowStatus",
    "BusinessPreconditionOperator",
    "BusinessPreconditionType",
    "BusinessRuleType",
    "BusinessVariableDataType",
    "BusinessVariableDirection",
]
