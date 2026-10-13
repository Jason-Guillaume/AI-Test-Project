"""环境配置模块：契约定义。

环境名会被写进执行记录等列（String(50)），因此长度限制与旧项目保持一致。
表为空时回退到内置环境（不落库、不可编辑），保证执行链路总能拿到可用环境。
"""

from __future__ import annotations

import os
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 环境名会被拼进 URL 与作为执行记录的外键值，限制为易读的短标识。
_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,49}$")


def normalize_environment_name(name: str) -> str:
    """校验并规范化环境名；非法值返回空串，由调用方转换为 422。"""
    value = (name or "").strip()
    if not _NAME_PATTERN.match(value):
        return ""
    return value


def builtin_environments() -> list[dict]:
    """内置的四个环境，用于首次建表前或表为空时回退。

    URL 可由 ENV_* 环境变量覆盖；代码中的 example.com 仅是未配置时的占位地址。
    """
    return [
        {
            "name": "dev",
            "display_name": "开发环境",
            "base_url": os.getenv("ENV_DEV_URL", "http://localhost:8000"),
            "gateway_prefix": "",
            "default_headers": {},
            "description": "本地开发环境",
            "is_default": True,
            "is_active": True,
        },
        {
            "name": "test",
            "display_name": "测试环境",
            "base_url": os.getenv("ENV_TEST_URL", "http://test-api.example.com"),
            "gateway_prefix": "",
            "default_headers": {},
            "description": "功能测试环境",
            "is_default": False,
            "is_active": True,
        },
        {
            "name": "staging",
            "display_name": "预发布环境",
            "base_url": os.getenv("ENV_STAGING_URL", "http://staging-api.example.com"),
            "gateway_prefix": "",
            "default_headers": {},
            "description": "预发布/灰度环境",
            "is_default": False,
            "is_active": True,
        },
        {
            "name": "prod",
            "display_name": "生产环境",
            "base_url": os.getenv("ENV_PROD_URL", ""),
            "gateway_prefix": "",
            "default_headers": {},
            "description": "生产环境（谨慎操作）",
            "is_default": False,
            "is_active": True,
        },
    ]


def _strip(value):
    """去掉字符串首尾空白；非字符串原样返回，供各 field_validator 复用。"""
    return value.strip() if isinstance(value, str) else value


class EnvironmentBase(BaseModel):
    """环境共有字段。"""

    name: str = Field(..., min_length=1, max_length=50, description="环境唯一标识，如 dev/test")
    display_name: str = Field(default="", max_length=100, description="展示名称")
    base_url: str = Field(default="", max_length=500, description="被测服务基础 URL")
    gateway_prefix: str = Field(default="", max_length=200, description="网关路径前缀")
    default_headers: dict = Field(default_factory=dict, description="该环境默认请求头")
    description: str | None = Field(default=None, max_length=1000, description="环境用途说明")
    is_default: bool = False
    is_active: bool = True

    @field_validator("name", "display_name", "base_url", "gateway_prefix", mode="before")
    @classmethod
    def strip_text(cls, value):
        """新建场景的入口清洗：环境名等标识字段先去掉首尾空白再校验。"""
        return _strip(value)


class EnvironmentCreate(EnvironmentBase):
    """新增环境入参。"""


class EnvironmentUpdate(BaseModel):
    """更新环境入参（局部）。name 不可修改。"""

    display_name: str | None = Field(default=None, max_length=100)
    base_url: str | None = Field(default=None, max_length=500)
    gateway_prefix: str | None = Field(default=None, max_length=200)
    default_headers: dict | None = Field(default=None)
    description: str | None = Field(default=None, max_length=1000)
    is_default: bool | None = None
    is_active: bool | None = None

    @field_validator("display_name", "base_url", "gateway_prefix", mode="before")
    @classmethod
    def strip_optional(cls, value):
        """局部更新场景的入口清洗；name 不在其中，因为环境名不可修改。"""
        return _strip(value)


class EnvironmentResponse(BaseModel):
    """环境响应。id 为空表示内置默认项，尚未落库、不可编辑。"""

    id: int | None = None
    name: str
    display_name: str
    base_url: str
    gateway_prefix: str
    default_headers: dict
    description: str | None = None
    is_default: bool
    is_active: bool
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class EnvironmentListResponse(BaseModel):
    """环境列表响应。"""

    total: int
    items: list[EnvironmentResponse]
    page: int = 1
    page_size: int = 1


__all__ = [
    "EnvironmentBase",
    "EnvironmentCreate",
    "EnvironmentListResponse",
    "EnvironmentResponse",
    "EnvironmentUpdate",
    "builtin_environments",
    "normalize_environment_name",
]
