"""模型配置模块：契约定义。

响应白名单绝不包含数据库密文或真实 API Key，只返回 has_api_key 与脱敏前缀。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 支持的模型供应商；未知值统一归一为 openai-compatible。
PROVIDERS: tuple[str, ...] = (
    "openai-compatible",
    "openai",
    "deepseek",
    "qwen",
    "anthropic",
)

# 供应商值到展示名的映射，供前端下拉直接渲染，避免前端再维护一份常量。
PROVIDER_LABELS: dict[str, str] = {
    "openai-compatible": "OpenAI 兼容",
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "qwen": "通义千问",
    "anthropic": "Anthropic",
}


def normalize_provider(provider: str | None) -> str:
    """把未知供应商名归一为 openai-compatible，避免脏数据阻断接口调用。"""
    value = (provider or "").strip().lower()
    return value if value in PROVIDERS else "openai-compatible"


def _strip(value):
    """去掉字符串首尾空白；非字符串原样返回，供各 field_validator 复用。"""
    return value.strip() if isinstance(value, str) else value


class ModelConfigurationBase(BaseModel):
    """模型配置共有字段。"""

    label: str = Field(..., min_length=1, max_length=120, description="前端展示名称")
    provider: str = Field(default="openai-compatible", max_length=50, description="模型供应商")
    api_base: str = Field(..., min_length=1, max_length=500, description="OpenAI 兼容接口根地址")
    model_name: str = Field(..., min_length=1, max_length=200, description="供应商模型名称")
    temperature: float = Field(default=0.2, ge=0, le=2, description="采样温度")
    max_tokens: int = Field(default=4096, ge=1, le=1_000_000, description="最大输出 Token")
    timeout: int = Field(default=60, ge=1, le=600, description="请求超时秒数")
    cost_per_1k_input: float = Field(default=0.0, ge=0, description="千输入 Token 成本")
    cost_per_1k_output: float = Field(default=0.0, ge=0, description="千输出 Token 成本")
    is_enabled: bool = True
    is_default: bool = False
    fallback_model_ids: list[int] = Field(default_factory=list, max_length=3, description="按顺序尝试的备用模型配置 ID")
    sort_order: int = 0

    @field_validator("label", "api_base", "model_name", "provider", mode="before")
    @classmethod
    def strip_text(cls, value):
        """新建场景的入口清洗：在类型校验前去掉文本字段首尾空白。"""
        return _strip(value)


class ModelConfigurationCreate(ModelConfigurationBase):
    """新增模型配置入参；api_key 为空表示该模型暂不可用。"""

    # 只写入不落响应：该字段绝不出现在任何 Response 模型里。
    api_key: str = Field(default="", max_length=1000, description="API Key，只写入不落响应")


class ModelConfigurationUpdate(BaseModel):
    """更新模型配置入参（局部）。

    api_key 为空或缺省表示保留已有密钥，只有显式传入非空值才覆盖。
    """

    label: str | None = Field(None, min_length=1, max_length=120)
    provider: str | None = Field(None, max_length=50)
    api_base: str | None = Field(None, min_length=1, max_length=500)
    api_key: str | None = Field(None, max_length=1000)
    model_name: str | None = Field(None, min_length=1, max_length=200)
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int | None = Field(None, ge=1, le=1_000_000)
    timeout: int | None = Field(None, ge=1, le=600)
    cost_per_1k_input: float | None = Field(None, ge=0)
    cost_per_1k_output: float | None = Field(None, ge=0)
    is_enabled: bool | None = None
    is_default: bool | None = None
    fallback_model_ids: list[int] | None = Field(None, max_length=3)
    sort_order: int | None = None

    @field_validator(
        "label", "api_base", "api_key", "model_name", "provider", mode="before"
    )
    @classmethod
    def strip_optional(cls, value):
        """局部更新场景的入口清洗：注意 api_key 也走这里，空串不会被判为非空。"""
        return _strip(value)


class ModelConfigurationResponse(BaseModel):
    """模型配置响应；不包含任何密钥明文。"""

    id: int
    domain_id: str = Field(..., description="后端生成的稳定引用 ID，供组织授权与模型路由使用")
    label: str
    provider: str
    api_base: str
    model_name: str
    temperature: float
    max_tokens: int
    timeout: int
    cost_per_1k_input: float
    cost_per_1k_output: float
    is_enabled: bool
    is_default: bool
    fallback_model_ids: list[int]
    sort_order: int
    # 只有布尔位，前端用它判断「是否需要填写密钥」，而不是拿到真实值。
    has_api_key: bool = False
    # 脱敏展示串（如 sk-a****abcd），用于展示与核对，不等于可用密钥。
    masked_api_key: str = ""
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModelConfigurationListResponse(BaseModel):
    """分页模型配置列表响应。"""

    total: int
    items: list[ModelConfigurationResponse]
    page: int = 1
    page_size: int = 1


class ProviderCatalogItem(BaseModel):
    """供应商目录项。"""

    value: str
    label: str


__all__ = [
    "ModelConfigurationBase",
    "ModelConfigurationCreate",
    "ModelConfigurationListResponse",
    "ModelConfigurationResponse",
    "ModelConfigurationUpdate",
    "PROVIDERS",
    "PROVIDER_LABELS",
    "ProviderCatalogItem",
    "normalize_provider",
]
