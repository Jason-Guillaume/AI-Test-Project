"""测试数据中心 + Data Factory 契约定义（Pydantic v2）。

只放请求/响应模型与字面量类型，不含业务逻辑；service 与 router 共用本文件作为
两层接口契约（与 test_management / business 的 schemas 风格一致）。

枚举在数据库层一律是 String（不设 sa.Enum / CHECK），合法取值由本文件的 Literal +
服务层校验决定；前端下拉与 Agent 提示词都从这里的常量取值。

安全约定：
- Provider 配置模型 `extra=forbid`，多出的键（尤其是 `sql`）直接 422（§10.1）。
- 响应体只暴露 `password_set`，绝不回显 password。
- 快照与 payload 在进入响应模型前已由 service 调 SensitiveDataMasker 脱敏。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FIXTURE_KEY_PATTERN = r"^[A-Z][A-Z0-9_]{0,99}$"

# --------------------------------------------------------------------------- 枚举字面量

FIXTURE_SCOPES = ("CASE", "RUN", "PROJECT", "GLOBAL")
FixtureScope = Literal["CASE", "RUN", "PROJECT", "GLOBAL"]

FIXTURE_STATUSES = ("DRAFT", "ACTIVE", "DISABLED")
FixtureStatus = Literal["DRAFT", "ACTIVE", "DISABLED"]

FIXTURE_CLEANUP_POLICIES = ("AFTER_CASE", "AFTER_RUN", "MANUAL", "NEVER")
FixtureCleanupPolicy = Literal["AFTER_CASE", "AFTER_RUN", "MANUAL", "NEVER"]

FIXTURE_PHASES = ("GENERATE", "CLEANUP")
FixturePhase = Literal["GENERATE", "CLEANUP"]

# 可执行步骤类型。
FIXTURE_STEP_TYPES_EXECUTABLE = (
    "FIXTURE", "API", "BUSINESS_ACTION", "BUSINESS_FLOW",
    "FAKER", "STATIC", "DATABASE_INSERT", "DATABASE_PATCH",
)
# 预留类型：只保存不执行，执行到即 FIXTURE_STEP_UNSUPPORTED。
FIXTURE_STEP_TYPES_RESERVED = ("WAIT", "DATABASE_QUERY", "EXTERNAL_PROVIDER")
FIXTURE_STEP_TYPES = FIXTURE_STEP_TYPES_EXECUTABLE + FIXTURE_STEP_TYPES_RESERVED
FixtureStepType = Literal[
    "FIXTURE", "API", "BUSINESS_ACTION", "BUSINESS_FLOW", "FAKER", "STATIC",
    "DATABASE_INSERT", "DATABASE_PATCH", "WAIT", "DATABASE_QUERY", "EXTERNAL_PROVIDER",
]

FIXTURE_ON_FAILURE = ("ABORT", "CONTINUE")
FixtureOnFailure = Literal["ABORT", "CONTINUE"]

VALUE_TYPES = ("STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY")
ValueType = Literal["STRING", "INTEGER", "NUMBER", "BOOLEAN", "OBJECT", "ARRAY"]

PROVIDER_TYPES = (
    "STATIC", "ENVIRONMENT", "FAKER", "API_CREATE",
    "BUSINESS_ACTION", "BUSINESS_FLOW", "EXISTING_POOL",
    "DATABASE_INSERT", "DATABASE_PATCH",
)
ProviderType = Literal[
    "STATIC", "ENVIRONMENT", "FAKER", "API_CREATE",
    "BUSINESS_ACTION", "BUSINESS_FLOW", "EXISTING_POOL",
    "DATABASE_INSERT", "DATABASE_PATCH",
]

RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

ASSET_SOURCES = ("STATIC", "POOL", "FIXTURE")
AssetSource = Literal["STATIC", "POOL", "FIXTURE"]

ASSET_STATUSES = ("ACTIVE", "DISABLED", "EXPIRED")
AssetStatus = Literal["ACTIVE", "DISABLED", "EXPIRED"]

POOL_STATUSES = ("ACTIVE", "DISABLED")
PoolStatus = Literal["ACTIVE", "DISABLED"]

POOL_ITEM_STATUSES = ("AVAILABLE", "OCCUPIED", "EXPIRED", "DISABLED")
PoolItemStatus = Literal["AVAILABLE", "OCCUPIED", "EXPIRED", "DISABLED"]

LEASE_STATUSES = ("ACTIVE", "RELEASED", "EXPIRED")
LeaseStatus = Literal["ACTIVE", "RELEASED", "EXPIRED"]

DB_OPERATIONS = ("INSERT", "UPDATE", "SELECT", "DELETE")
DbOperation = Literal["INSERT", "UPDATE", "SELECT", "DELETE"]

# 环境归类结果（由 db_guard 按 Environment.name 整词相等判定，未知 → STAGING）。
DB_ENV_CLASSES = ("DEV", "TEST", "STAGING", "PRODUCTION")
DbEnvironmentClass = Literal["DEV", "TEST", "STAGING", "PRODUCTION"]

# 造数主状态（data_execution / fixture_execution 同一套）。
DATA_EXECUTION_STATUSES = (
    "PENDING", "GENERATING", "READY", "FAILED", "EXPIRED", "DIRTY", "CLEANING", "CLEANED",
)
DataExecutionStatus = Literal[
    "PENDING", "GENERATING", "READY", "FAILED", "EXPIRED", "DIRTY", "CLEANING", "CLEANED",
]

PROVIDER_EXECUTION_STATUSES = ("PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED")
ProviderExecutionStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "SKIPPED"]

CLEANUP_STATUSES = ("PENDING", "SUCCESS", "FAILED", "SKIPPED")
CleanupStatus = Literal["PENDING", "SUCCESS", "FAILED", "SKIPPED"]

FAKER_GENERATORS = (
    "uuid", "name", "phone", "email", "string", "integer",
    "timestamp", "date", "url", "ip", "random_choice", "project_name",
)
FAKER_LOCALES = ("zh_CN", "en_US")

# 模板解析命名空间（VariableResolver）。
RESOLVE_NAMESPACES = ("fixture", "faker", "env", "runtime", "data")

# 输入映射写入位置（与 business.executors.mapping_resolver 的语义一致）。
MAPPING_LOCATIONS = ("HEADER", "QUERY", "PATH", "BODY", "COOKIE")
MappingLocation = Literal["HEADER", "QUERY", "PATH", "BODY", "COOKIE"]


# --------------------------------------------------------------------------- 通用

class PageResponse(BaseModel):
    """分页壳（由各列表响应的 items 承载具体类型）。"""

    page: int
    page_size: int
    total: int


# --------------------------------------------------------------------------- 固定数据 Fixture


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


class FixtureStepInput(BaseModel):
    """步骤写入入参（整体替换时批量提交）。"""

    phase: FixturePhase = Field(default="GENERATE")
    step_type: FixtureStepType
    name: str = Field(..., min_length=1, max_length=200)
    sort: int = Field(default=0, ge=0)
    provider_id: int | None = None
    config_json: dict[str, Any] | None = None
    on_failure: FixtureOnFailure = Field(default="ABORT")


class FixtureStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fixture_id: int
    phase: str
    step_type: str
    name: str
    sort: int
    provider_id: int | None = None
    config_json: dict[str, Any] | None = None
    on_failure: str


class FixtureOutputInput(BaseModel):
    """输出契约写入入参。"""

    name: str = Field(..., min_length=1, max_length=100)
    value_type: ValueType = Field(default="STRING")
    source_path: str = Field(..., min_length=1, max_length=200, description="从私有上下文取值：task_id 或 $.data.id")
    description: str | None = Field(None, max_length=500)
    sort: int = Field(default=0, ge=0)


class FixtureOutputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fixture_id: int
    name: str
    value_type: str
    source_path: str
    description: str | None = None
    sort: int


class FixtureDependencyResponse(BaseModel):
    """依赖边响应，附带被依赖方的名称与 key，便于前端直接画树。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    fixture_id: int
    depends_on_fixture_id: int
    sort: int
    depends_on_key: str | None = None
    depends_on_name: str | None = None
    depends_on_entity_type: str | None = None


class FixtureCreate(BaseModel):
    """整体创建：基本信息 + 步骤 + 输出契约 + 依赖。"""

    name: str = Field(..., min_length=1, max_length=200)
    fixture_key: str = Field(..., min_length=1, max_length=100)
    entity_type: str = Field(..., min_length=1, max_length=50)
    description: str | None = Field(None, max_length=1000)
    scope: FixtureScope = "CASE"
    status: FixtureStatus = "DRAFT"
    cache_enabled: bool = True
    cleanup_policy: FixtureCleanupPolicy = "AFTER_CASE"
    steps: list[FixtureStepInput] = Field(default_factory=list)
    outputs: list[FixtureOutputInput] = Field(default_factory=list)
    dependencies: list[int] = Field(default_factory=list, description="依赖的 Fixture ID 列表")

    @field_validator("fixture_key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        """检查键。"""
        import re

        if not re.fullmatch(FIXTURE_KEY_PATTERN, v):
            raise ValueError("fixture_key 必须匹配 " + FIXTURE_KEY_PATTERN)
        return v

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        """检查名称。"""
        return v.strip()


class FixtureUpdate(BaseModel):
    """PATCH：只改基本信息，不动步骤/输出/依赖。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    scope: FixtureScope | None = None
    status: FixtureStatus | None = None
    cache_enabled: bool | None = None
    cleanup_policy: FixtureCleanupPolicy | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        """检查名称。"""
        return v.strip() if v is not None else v


class FixtureStepsReplace(BaseModel):
    """整体替换步骤：同时提交 GENERATE 与 CLEANUP，后端重建依赖边并跑环检测。"""

    steps: list[FixtureStepInput] = Field(default_factory=list)


class FixtureOutputsReplace(BaseModel):
    """整体替换输出契约。"""

    outputs: list[FixtureOutputInput] = Field(default_factory=list)


class FixtureBriefResponse(BaseModel):
    """列表响应：只带必要字段 + 输出名，避免把步骤配置整包推给前端。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    fixture_key: str
    entity_type: str
    description: str | None = None
    scope: str
    status: str
    cache_enabled: bool
    cleanup_policy: str
    output_names: list[str] = Field(default_factory=list)
    step_count: int = 0
    generate_step_count: int = 0
    cleanup_step_count: int = 0
    dependency_count: int = 0
    referenced_case_count: int = 0
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class FixtureDetailResponse(FixtureBriefResponse):
    """详情：基本信息 + 步骤 + 输出契约 + 依赖 + 引用它的用例。"""

    steps: list[FixtureStepResponse] = Field(default_factory=list)
    outputs: list[FixtureOutputResponse] = Field(default_factory=list)
    dependencies: list[FixtureDependencyResponse] = Field(default_factory=list)
    referenced_cases: list[dict[str, Any]] = Field(default_factory=list)


class FixtureTreeNodeResponse(BaseModel):
    """依赖树节点（含子依赖），用于左树与依赖 Tab。"""

    id: int
    fixture_key: str
    name: str
    entity_type: str
    scope: str
    status: str
    depth: int = 0
    children: list["FixtureTreeNodeResponse"] = Field(default_factory=list)


class FixtureGenerateRequest(BaseModel):
    """手工试跑：只指定环境，不挂 TestRun。"""

    environment_id: int = Field(..., description="本次试跑使用的环境")
    scope: FixtureScope = "CASE"
    variables: dict[str, Any] = Field(default_factory=dict, description="试跑注入的初始变量")


# --------------------------------------------------------------------------- 测试数据目录


class TestDataAssetCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    entity_type: str = Field(..., min_length=1, max_length=50)
    source: AssetSource = "STATIC"
    scope: FixtureScope = "PROJECT"
    status: AssetStatus = "ACTIVE"
    fixture_id: int | None = None
    value_json: dict[str, Any] | None = None
    description: str | None = Field(None, max_length=500)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        """检查名称。"""
        return v.strip()


class TestDataAssetUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    entity_type: str | None = Field(None, min_length=1, max_length=50)
    source: AssetSource | None = None
    scope: FixtureScope | None = None
    status: AssetStatus | None = None
    fixture_id: int | None = None
    value_json: dict[str, Any] | None = None
    description: str | None = Field(None, max_length=500)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        """检查名称。"""
        return v.strip() if v is not None else v


class TestDataAssetResponse(BaseModel):
    """响应体的 value_json 已由 service 脱敏；掩码值编辑时留空表示不修改。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    entity_type: str
    source: str
    scope: str
    status: str
    fixture_id: int | None = None
    value_json: dict[str, Any] | None = None
    description: str | None = None
    referenced_count: int = 0
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- 数据提供器 数据提供器 Data Provider

# Provider 配置统一 `extra=forbid`：配置里出现 sql 等未声明键直接 422（§10.1）。
class _StrictConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StaticProviderConfig(_StrictConfig):
    values: dict[str, Any] = Field(default_factory=dict, description="原样写入上下文的字面量")


class EnvironmentProviderConfig(_StrictConfig):
    key: str = Field(..., min_length=1, max_length=100, description="环境键：base_url / gateway_prefix / default_headers 的键")


class FakerProviderConfig(_StrictConfig):
    generator: str = Field(..., description="白名单生成器：uuid/name/phone/email/...")
    locale: str = Field(default="zh_CN", description="仅 zh_CN / en_US")
    output_key: str | None = Field(None, max_length=100, description="写入私有上下文的键名")
    choices: list[str | int] | None = Field(None, description="random_choice 专用，元素只能是字符串或数字")


class ApiCreateProviderConfig(_StrictConfig):
    api_id: int = Field(..., description="接口 ID（不建 FK，执行时校验归属与状态）")
    input_mappings: list[MappingRule] = Field(default_factory=list)
    output_mappings: list[OutputMapping] = Field(default_factory=list)
    cleanup: CleanupBinding | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict, description="静态请求体，可与 input_mappings 合并")
    environment_id: int | None = Field(None, description="可选；若填写必须与本次运行环境一致")


class BusinessActionProviderConfig(_StrictConfig):
    business_action_id: int | None = None
    flow_id: int | None = None
    action_key: str | None = Field(None, max_length=200)


class BusinessFlowProviderConfig(_StrictConfig):
    business_flow_id: int
    input_variables: dict[str, Any] = Field(default_factory=dict)
    environment_id: int | None = Field(None, description="可选；若填写必须与本次运行环境一致")


class PoolProviderConfig(_StrictConfig):
    pool_key: str = Field(..., min_length=1, max_length=100)


class DatabaseProviderConfig(_StrictConfig):
    """结构化数据库操作。禁止 sql 字符串字段，禁止多表。"""

    connection_id: int = Field(..., description="目标库连接 ID")
    table: str = Field(..., min_length=1, max_length=64, description="表名（裸标识符，白名单校验）")
    operation: DbOperation = "INSERT"
    columns: list[str] = Field(default_factory=list, description="INSERT 专用列名")
    values: dict[str, Any] = Field(default_factory=dict, description="写入值（全部走占位符）")
    where: dict[str, Any] = Field(default_factory=dict, description="UPDATE/SELECT/DELETE 条件")
    limit: int | None = Field(None, ge=1, le=20, description="SELECT 专用，默认 1，最大 20")
    allow_delete: bool = Field(default=False, description="DELETE 需策略白名单 + CRITICAL 三重确认")


PROVIDER_CONFIG_MODELS: dict[str, type[BaseModel]] = {
    "STATIC": StaticProviderConfig,
    "ENVIRONMENT": EnvironmentProviderConfig,
    "FAKER": FakerProviderConfig,
    "API_CREATE": ApiCreateProviderConfig,
    "BUSINESS_ACTION": BusinessActionProviderConfig,
    "BUSINESS_FLOW": BusinessFlowProviderConfig,
    "EXISTING_POOL": PoolProviderConfig,
    "DATABASE_INSERT": DatabaseProviderConfig,
    "DATABASE_PATCH": DatabaseProviderConfig,
}


class DataProviderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    provider_type: ProviderType
    config_json: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    risk_level: RiskLevel | None = Field(None, description="缺省按 provider_type 推断，允许调高")
    description: str | None = Field(None, max_length=1000)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        """检查名称。"""
        return v.strip()


class DataProviderUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    provider_type: ProviderType | None = None
    config_json: dict[str, Any] | None = None
    enabled: bool | None = None
    risk_level: RiskLevel | None = None
    description: str | None = Field(None, max_length=1000)

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        """检查名称。"""
        return v.strip() if v is not None else v


class DataProviderResponse(BaseModel):
    """config_json 不含密码；DATABASE 类只回 connection_id，不回连接串。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    provider_type: str
    config_json: dict[str, Any]
    enabled: bool
    risk_level: str
    description: str | None = None
    usage_count: int = 0
    last_status: str | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class DataProviderTestRequest(BaseModel):
    environment_id: int = Field(..., description="试跑使用的环境")
    variables: dict[str, Any] = Field(default_factory=dict, description="可选注入变量")


# --------------------------------------------------------------------------- 数据池


class DataPoolCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    pool_key: str = Field(..., min_length=1, max_length=100)
    asset_id: int | None = None
    scope: FixtureScope = "PROJECT"
    max_concurrency: int = Field(default=1, ge=1, le=1000)
    lease_ttl_seconds: int = Field(default=1800, ge=1, le=86400)
    status: PoolStatus = "ACTIVE"

    @field_validator("pool_key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        """检查键。"""
        import re

        if not re.fullmatch(FIXTURE_KEY_PATTERN, v):
            raise ValueError("pool_key 必须匹配 " + FIXTURE_KEY_PATTERN)
        return v

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        """检查名称。"""
        return v.strip()


class DataPoolUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    max_concurrency: int | None = Field(None, ge=1, le=1000)
    lease_ttl_seconds: int | None = Field(None, ge=1, le=86400)
    status: PoolStatus | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        """检查名称。"""
        return v.strip() if v is not None else v


class DataPoolResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    asset_id: int | None = None
    pool_key: str
    name: str
    scope: str
    max_concurrency: int
    lease_ttl_seconds: int
    status: str
    item_count: int = 0
    available_count: int = 0
    active_lease_count: int = 0
    created_at: datetime
    updated_at: datetime


class DataPoolItemCreate(BaseModel):
    payload_json: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    status: PoolItemStatus = "AVAILABLE"


class DataPoolItemUpdate(BaseModel):
    status: PoolItemStatus | None = None
    payload_json: dict[str, Any] | None = None
    expires_at: datetime | None = None


class DataPoolItemResponse(BaseModel):
    """payload_json 已脱敏。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    pool_id: int
    status: str
    payload_json: dict[str, Any]
    occupied_count: int
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DataPoolLeaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    item_id: int
    project_id: int
    test_run_id: int | None = None
    case_execution_id: int | None = None
    status: str
    leased_at: datetime | None = None
    released_at: datetime | None = None
    expires_at: datetime | None = None


# --------------------------------------------------------------------------- 被测库与策略


class TargetDbConnectionCreate(BaseModel):
    """创建时唯一一次明文 password；服务端加密后只存密文。"""

    environment_id: int
    name: str = Field(..., min_length=1, max_length=200)
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database_name: str = Field(..., min_length=1, max_length=128)
    username: str = Field(..., min_length=1, max_length=128)
    password: str = Field(..., min_length=1, max_length=512)
    schema_name: str | None = Field(None, max_length=128)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        """检查名称。"""
        return v.strip()


class TargetDbConnectionUpdate(BaseModel):
    """password 缺省表示不改。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    host: str | None = Field(None, min_length=1, max_length=255)
    port: int | None = Field(None, ge=1, le=65535)
    database_name: str | None = Field(None, min_length=1, max_length=128)
    username: str | None = Field(None, min_length=1, max_length=128)
    password: str | None = Field(None, min_length=1, max_length=512)
    schema_name: str | None = Field(None, max_length=128)
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        """检查名称。"""
        return v.strip() if v is not None else v


class TargetDbConnectionResponse(BaseModel):
    """只有 password_set，没有 password 字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    environment_id: int
    environment_name: str | None = None
    environment_class: str | None = None
    name: str
    host: str
    port: int
    database_name: str
    username: str
    schema_name: str | None = None
    enabled: bool
    password_set: bool = True
    referenced_count: int = 0
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class DatabasePolicyUpsert(BaseModel):
    """设置策略：enabled + 表白名单 + 操作白名单。

    PRODUCTION 归类的环境 PUT enabled=true → 400 DATABASE_ENVIRONMENT_FORBIDDEN。
    """

    enabled: bool
    allowed_tables: list[str] = Field(default_factory=list)
    allowed_operations: list[DbOperation] = Field(default_factory=lambda: ["INSERT", "UPDATE", "SELECT"])


class DatabasePolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    environment_id: int
    enabled: bool
    allowed_tables: list[str]
    allowed_operations: list[str]
    environment_name: str | None = None
    environment_display_name: str | None = None
    # 计算字段：service 在 model_validate 后覆写；缺省 STAGING 仅让 ORM→响应转换不报缺失。
    environment_class: str = "STAGING"
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- 执行记录


class ProviderExecutionResponse(BaseModel):
    """input_snapshot / output_snapshot 已脱敏；`_cleanup` 保留键不进入契约输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    fixture_execution_id: int | None = None
    data_execution_id: int | None = None
    project_id: int
    provider_id: int | None = None
    provider_type: str
    step_id: int | None = None
    status: str
    input_snapshot: dict[str, Any] | None = None
    output_snapshot: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    cleanup_status: str | None = None


class FixtureExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    data_execution_id: int
    project_id: int
    fixture_id: int | None = None
    fixture_key: str
    status: str
    scope: str
    cache_hit: bool
    input_snapshot: dict[str, Any] | None = None
    output_snapshot: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    cleanup_status: str | None = None
    cleanup_error_code: str | None = None
    cleanup_error_message: str | None = None
    provider_executions: list[ProviderExecutionResponse] = Field(default_factory=list)


class DataExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    test_run_id: int | None = None
    case_execution_id: int | None = None
    environment_id: int | None = None
    status: str
    scope: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    cleanup_status: str | None = None
    cleanup_error_code: str | None = None
    cleanup_error_message: str | None = None
    fixture_key_count: int = 0
    provider_step_count: int = 0
    created_at: datetime


class DataExecutionDetailResponse(DataExecutionResponse):
    """详情：总记录 + Fixture 执行链 + 每步 Provider 执行的 input/output/error。

    ``provider_executions`` 是**没有归属 Fixture** 的步骤记录——手工试跑单个
    Provider 时 ``fixture_execution_id`` 为空，只能挂在这一层。
    """

    fixture_executions: list[FixtureExecutionResponse] = Field(default_factory=list)
    provider_executions: list[ProviderExecutionResponse] = Field(default_factory=list)


# --------------------------------------------------------------------------- 分页包装


class FixtureListResponse(BaseModel):
    items: list[FixtureBriefResponse]
    page: int
    page_size: int
    total: int


class TestDataAssetListResponse(BaseModel):
    items: list[TestDataAssetResponse]
    page: int
    page_size: int
    total: int


class DataProviderListResponse(BaseModel):
    items: list[DataProviderResponse]
    page: int
    page_size: int
    total: int


class DataPoolListResponse(BaseModel):
    items: list[DataPoolResponse]
    page: int
    page_size: int
    total: int


class DataPoolItemListResponse(BaseModel):
    items: list[DataPoolItemResponse]
    page: int
    page_size: int
    total: int


class DataPoolLeaseListResponse(BaseModel):
    items: list[DataPoolLeaseResponse]
    page: int
    page_size: int
    total: int


class TargetDbConnectionListResponse(BaseModel):
    items: list[TargetDbConnectionResponse]
    page: int
    page_size: int
    total: int


class DatabasePolicyListResponse(BaseModel):
    items: list[DatabasePolicyResponse]
    page: int
    page_size: int
    total: int


class DataExecutionListResponse(BaseModel):
    items: list[DataExecutionResponse]
    page: int
    page_size: int
    total: int


FixtureTreeNodeResponse.model_rebuild()
