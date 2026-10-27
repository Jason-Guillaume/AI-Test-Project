"""Agent 治理配置 API 契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.features.agent_governance.catalog import WORKFLOW_TEMPLATES


class AgentDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    workflow_template: str
    instruction: str = Field(default="", max_length=12000)
    model_config_id: int | None = Field(default=None, ge=1)
    skill_keys: list[str] = Field(default_factory=list, max_length=30)
    tool_keys: list[str] = Field(default_factory=list, max_length=50)
    child_agent_ids: list[int] = Field(default_factory=list, max_length=8)
    is_enabled: bool = False

    @field_validator("name", "description", "instruction", mode="before")
    @classmethod
    def strip_text(cls, value):
        """清理文本。"""
        return value.strip() if isinstance(value, str) else value

    @field_validator("workflow_template")
    @classmethod
    def known_template(cls, value: str):
        """判断工作流名称是否属于内置模板。"""
        if value not in WORKFLOW_TEMPLATES:
            raise ValueError("请选择平台支持的工作流模板")
        return value


class AgentDefinitionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    workflow_template: str | None = None
    instruction: str | None = Field(default=None, max_length=12000)
    model_config_id: int | None = Field(default=None, ge=1)
    skill_keys: list[str] | None = Field(default=None, max_length=30)
    tool_keys: list[str] | None = Field(default=None, max_length=50)
    child_agent_ids: list[int] | None = Field(default=None, max_length=8)
    is_enabled: bool | None = None

    @field_validator("name", "description", "instruction", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        """清理可选文本。"""
        return value.strip() if isinstance(value, str) else value

    @field_validator("workflow_template")
    @classmethod
    def known_template(cls, value: str | None):
        """判断工作流名称是否属于内置模板。"""
        if value is not None and value not in WORKFLOW_TEMPLATES:
            raise ValueError("请选择平台支持的工作流模板")
        return value


class AgentDefinitionResponse(BaseModel):
    id: int
    key: str
    name: str
    description: str
    workflow_template: str
    instruction: str
    model_config_id: int | None
    skill_keys: list[str]
    tool_keys: list[str]
    child_agent_ids: list[int]
    is_enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    content: str = Field(min_length=1, max_length=50000)
    is_enabled: bool = False

    @field_validator("name", "description", "content", mode="before")
    @classmethod
    def strip_text(cls, value):
        """清理文本。"""
        return value.strip() if isinstance(value, str) else value


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    content: str | None = Field(default=None, min_length=1, max_length=50000)
    is_enabled: bool | None = None

    @field_validator("name", "description", "content", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        """清理可选文本。"""
        return value.strip() if isinstance(value, str) else value


class SkillResponse(BaseModel):
    id: int
    key: str
    name: str
    description: str
    content: str
    is_enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MCPServerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    endpoint: str = Field(min_length=1, max_length=1000)
    auth_type: Literal["none", "bearer"] = "none"
    auth_token: str = Field(default="", max_length=4000)
    is_enabled: bool = False

    @field_validator("name", "endpoint", mode="before")
    @classmethod
    def strip_text(cls, value):
        """清理文本。"""
        return value.strip() if isinstance(value, str) else value

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str):
        """校验接口。"""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("MCP 地址必须是 HTTP 或 HTTPS URL")
        if parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ValueError("MCP 地址不能包含账号密码、查询参数或 URL 片段")
        return value

    @model_validator(mode="after")
    def require_token(self):
        """校验请求中是否提供必需的令牌。"""
        if self.auth_type == "bearer" and not self.auth_token:
            raise ValueError("Bearer 认证需要填写访问令牌")
        return self


class MCPServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    endpoint: str | None = Field(default=None, min_length=1, max_length=1000)
    auth_type: Literal["none", "bearer"] | None = None
    auth_token: str | None = Field(default=None, max_length=4000)
    is_enabled: bool | None = None

    @field_validator("name", "endpoint", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        """清理可选文本。"""
        return value.strip() if isinstance(value, str) else value

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str | None):
        """校验接口。"""
        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or parsed.query:
            raise ValueError("请输入有效的 HTTP/HTTPS MCP 地址，且不能带认证信息、查询参数或 URL 片段")
        return value


class MCPServerResponse(BaseModel):
    id: int
    name: str
    endpoint: str
    auth_type: str
    has_auth: bool
    is_enabled: bool
    connection_status: str
    discovered_tools_json: list[dict]
    approved_tools_json: list[str]
    last_checked_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class MCPApprovalUpdate(BaseModel):
    tool_names: list[str] = Field(default_factory=list, max_length=100)


class DefinitionVersionResponse(BaseModel):
    version: int
    snapshot_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
