"""接口管理模块：契约定义（Pydantic v2）。

集中存放：枚举字面量、Internal API Schema（统一中间表示）、CRUD 请求/响应模型、
导入预览/确认 DTO、调试请求/响应。service 与 router 共享本文件类型，作为两层接口契约。

字段一律 snake_case，与 ORM 模型对齐。本文件不含业务逻辑。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ----------------------------------------------------------------------------- 枚举

ApiStatus = Literal["ACTIVE", "DRAFT", "DEPRECATED", "DEVELOPING", "MOCK"]
ApiSourceType = Literal["MANUAL", "CURL", "OPENAPI", "SWAGGER", "POSTMAN", "APIFOX"]
ParamLocation = Literal["PATH", "QUERY", "HEADER", "COOKIE", "BODY"]
BodyType = Literal["none", "json", "form", "multipart", "raw"]
RelationType = Literal["PRECONDITION", "OUTPUT_INPUT", "FOLLOW_UP"]
ChangeType = Literal[
    "CREATED",
    "UPDATED",
    "PARAM_ADDED",
    "PARAM_REMOVED",
    "PARAM_TYPE_CHANGED",
    "REQUIRED_CHANGED",
    "RESPONSE_CHANGED",
    "MODULE_CHANGED",
]
ImportClassification = Literal["NEW", "EXISTING", "CHANGED", "UNCHANGED"]

# 合法取值集合，供服务层入参校验复用。
API_STATUSES = {"ACTIVE", "DRAFT", "DEPRECATED", "DEVELOPING", "MOCK"}
API_SOURCE_TYPES = {"MANUAL", "CURL", "OPENAPI", "SWAGGER", "POSTMAN", "APIFOX"}
PARAM_LOCATIONS = {"PATH", "QUERY", "HEADER", "COOKIE", "BODY"}
BODY_TYPES = {"none", "json", "form", "multipart", "raw"}
RELATION_TYPES = {"PRECONDITION", "OUTPUT_INPUT", "FOLLOW_UP"}

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}


# ----------------------------------------------------------------------------- Internal API 接口 Schema（统一中间表示）

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


# ----------------------------------------------------------------------------- 模块 CRUD

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


# ----------------------------------------------------------------------------- 接口 CRUD

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

    status_code: int = Field(..., ge=100, le=599)
    description: str | None = None
    schema_json: dict[str, Any] | None = None
    example_json: str | None = None
    sort: int = 0


class ApiInterfaceCreate(BaseModel):
    """手工创建接口。"""

    module_id: int | None = Field(default=None, gt=0)
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    method: str
    path: str = Field(..., min_length=1, max_length=500)
    auth_type: str = "none"
    content_type: str = "application/json"
    status: ApiStatus = "DRAFT"
    parameters: list[ApiParameterIn] = Field(default_factory=list)
    body: ApiBodyIn = Field(default_factory=ApiBodyIn)
    responses: list[ApiResponseIn] = Field(default_factory=list)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: Any) -> str:
        """清理名称。"""
        return str(v or "").strip()

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, v: Any) -> str:
        """规范化方法。"""
        return str(v or "").upper()


class ApiInterfaceUpdate(BaseModel):
    """更新接口基本信息（局部）。"""

    module_id: int | None = Field(default=None, gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    method: str | None = None
    path: str | None = Field(default=None, min_length=1, max_length=500)
    auth_type: str | None = None
    content_type: str | None = None
    status: ApiStatus | None = None

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, v: Any) -> Any:
        """清理名称。"""
        return str(v).strip() if v is not None else None

    @field_validator("method", mode="before")
    @classmethod
    def normalize_method(cls, v: Any) -> Any:
        """规范化方法。"""
        return str(v).upper() if v is not None else None


class ApiInterfaceMove(BaseModel):
    """移动接口到指定模块。"""

    module_id: int | None = Field(default=None, gt=0)


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
    status_code: int
    description: str | None = None
    schema_json: dict[str, Any] | None = None
    example_json: str | None = None
    sort: int = 0

    model_config = ConfigDict(from_attributes=True)


class ApiInterfaceResponse(BaseModel):
    """接口列表/详情响应（基本信息）。"""

    id: int
    project_id: int
    module_id: int | None = None
    module_name: str | None = None
    name: str
    description: str | None = None
    method: str
    path: str
    auth_type: str
    content_type: str
    status: ApiStatus
    source_type: ApiSourceType
    version: int
    source_hash: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiInterfaceDetailResponse(ApiInterfaceResponse):
    """接口详情：附带参数、body、响应概要。"""

    parameters: list[ApiParameterResponse] = Field(default_factory=list)
    body: ApiRequestBodyResponse | None = None
    responses: list[ApiResponseResponse] = Field(default_factory=list)


class ApiInterfaceListResponse(BaseModel):
    """接口列表分页响应。"""

    items: list[ApiInterfaceResponse]
    total: int
    page: int = 1
    page_size: int = 20


# ----------------------------------------------------------------------------- 请求参数/响应整体替换

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


# ----------------------------------------------------------------------------- 关联

class ApiRelationCreate(BaseModel):
    """新增接口关联。"""

    source_api_id: int = Field(..., gt=0)
    target_api_id: int = Field(..., gt=0)
    relation_type: RelationType
    variable_name: str | None = Field(default=None, max_length=100)
    extract_path: str | None = Field(default=None, max_length=500)


class ApiRelationResponse(BaseModel):
    """关联响应。"""

    id: int
    project_id: int
    source_api_id: int
    target_api_id: int
    source_api_name: str | None = None
    target_api_name: str | None = None
    relation_type: RelationType
    variable_name: str | None = None
    extract_path: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiRelationListResponse(BaseModel):
    """关联列表响应。"""

    items: list[ApiRelationResponse]
    total: int


# ----------------------------------------------------------------------------- 变更记录

class ApiChangeLogResponse(BaseModel):
    """变更记录响应。"""

    id: int
    interface_id: int
    change_type: ChangeType
    diff_json: dict[str, Any] | None = None
    source_hash_before: str | None = None
    source_hash_after: str | None = None
    summary: str | None = None
    created_by: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiChangeLogListResponse(BaseModel):
    """变更记录列表响应。"""

    items: list[ApiChangeLogResponse]
    total: int


# ----------------------------------------------------------------------------- 导入预览/确认

class ImportPreviewRequest(BaseModel):
    """导入预览请求。content 为 curl 串或 openapi/swagger 文本。"""

    source_type: ApiSourceType
    content: str = Field(..., min_length=1)
    file_name: str | None = None
    user_module_id: int | None = Field(default=None, gt=0)
    tag_to_module_map: dict[str, int] | None = None


class ImportPreviewItem(BaseModel):
    """单条导入预览项。"""

    classification: ImportClassification
    schema: InternalApiSchema
    proposed_module_id: int | None = None
    proposed_module_name: str
    existing_interface_id: int | None = None
    diff_summary: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)


class ImportPreviewResponse(BaseModel):
    """导入预览响应（不入库）。"""

    project_id: int
    source_type: ApiSourceType
    source_hash: str | None = None
    total: int
    new_count: int
    existing_count: int
    changed_count: int
    unchanged_count: int
    items: list[ImportPreviewItem]


class ImportConfirmRequest(BaseModel):
    """导入确认请求。重新解析+去重+入库（幂等，不信任预览缓存）。"""

    source_type: ApiSourceType
    content: str = Field(..., min_length=1)
    file_name: str | None = None
    user_module_id: int | None = Field(default=None, gt=0)
    tag_to_module_map: dict[str, int] | None = None
    # selected_items：选中的预览项序号（0-based）；None 表示全部 NEW+CHANGED 项。
    selected_items: list[int] | None = None
    overwrite_changed: bool = True


class ImportConfirmResponse(BaseModel):
    """导入确认响应。"""

    record_id: int
    total: int
    created_count: int
    updated_count: int
    skipped_count: int
    source_hash: str | None = None


class ApiImportRecordResponse(BaseModel):
    """导入记录响应。"""

    id: int
    project_id: int
    source_type: ApiSourceType
    file_name: str | None = None
    source_hash: str | None = None
    total: int
    created_count: int
    updated_count: int
    skipped_count: int
    created_by: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApiImportRecordListResponse(BaseModel):
    """导入记录列表响应。"""

    items: list[ApiImportRecordResponse]
    total: int


# ----------------------------------------------------------------------------- 调试

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


__all__ = [
    "API_STATUSES",
    "API_SOURCE_TYPES",
    "PARAM_LOCATIONS",
    "BODY_TYPES",
    "RELATION_TYPES",
    "HTTP_METHODS",
    "ApiStatus",
    "ApiSourceType",
    "ParamLocation",
    "BodyType",
    "RelationType",
    "ChangeType",
    "ImportClassification",
    "InternalParameter",
    "InternalBody",
    "InternalResponse",
    "InternalApiSchema",
    "ApiModuleCreate",
    "ApiModuleUpdate",
    "ApiModuleMove",
    "ApiModuleResponse",
    "ApiParameterIn",
    "ApiBodyIn",
    "ApiResponseIn",
    "ApiInterfaceCreate",
    "ApiInterfaceUpdate",
    "ApiInterfaceMove",
    "ApiParameterResponse",
    "ApiRequestBodyResponse",
    "ApiResponseResponse",
    "ApiInterfaceResponse",
    "ApiInterfaceDetailResponse",
    "ApiInterfaceListResponse",
    "ApiRequestBundle",
    "ApiRequestBundleResponse",
    "ApiResponsesBundle",
    "ApiResponsesBundleResponse",
    "ApiRelationCreate",
    "ApiRelationResponse",
    "ApiRelationListResponse",
    "ApiChangeLogResponse",
    "ApiChangeLogListResponse",
    "ImportPreviewRequest",
    "ImportPreviewItem",
    "ImportPreviewResponse",
    "ImportConfirmRequest",
    "ImportConfirmResponse",
    "ApiImportRecordResponse",
    "ApiImportRecordListResponse",
    "ApiDebugRequest",
    "ApiDebugResponse",
]
