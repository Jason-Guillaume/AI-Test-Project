"""test_data 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.features.test_data.schemas.configuration import CleanupBinding
from app.features.test_data.schemas.common import DbOperation
from app.features.test_data.schemas.configuration import MappingRule
from app.features.test_data.schemas.configuration import OutputMapping
from app.features.test_data.schemas.common import ProviderType
from app.features.test_data.schemas.common import RiskLevel


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


class DataProviderListResponse(BaseModel):
    items: list[DataProviderResponse]
    page: int
    page_size: int
    total: int
