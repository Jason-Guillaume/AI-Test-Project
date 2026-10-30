"""test_data 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.features.test_data.schemas.common import DbOperation


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
