"""Agent 治理配置 API 契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.features.agent_governance.catalog import WORKFLOW_TEMPLATES


class AgentRuntimeSettings(BaseModel):
    """可随 Agent 版本保存的运行配置；默认值兼容既有固定任务工作流。"""

    model_binding: Literal["task_or_global", "agent"] = "task_or_global"
    max_loop_count: int = Field(default=0, ge=0, le=1000)
    timeout_seconds: int = Field(default=1200, ge=0, le=86400)
    network_search_enabled: bool = False
    interactive_shell_enabled: bool = False
    close_step_prompt: str = Field(default="", max_length=12000)
    close_step_max_loops: int = Field(default=0, ge=0, le=20)
    close_task_timeout_prompt: str = Field(default="", max_length=12000)
    close_task_timeout_max_loops: int = Field(default=0, ge=0, le=20)
    runtime_variables: list[dict[str, str]] = Field(default_factory=list, max_length=50)


class AgentTrigger(BaseModel):
    """事件触发器的可编辑定义。"""

    id: str = Field(min_length=1, max_length=80)
    event: Literal[
        "schedule", "finding.discovered", "objective.achieved", "task.timeout", "tool.call", "task.created",
    ]
    enabled: bool = False
    message: str = Field(default="", max_length=4000)
    schedule: str = Field(default="", max_length=120)
    tool_keys: list[str] = Field(default_factory=list, max_length=50)
    queue_policy: Literal["serial", "parallel"] = "serial"
    coalesce_by: Literal["task", "all", "none"] = "task"
    max_concurrency: int = Field(default=1, ge=1, le=50)


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
    settings_json: dict[str, Any] = Field(default_factory=dict)
    triggers_json: list[AgentTrigger] = Field(default_factory=list, max_length=30)

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

    @field_validator("settings_json")
    @classmethod
    def validate_settings(cls, value: dict[str, Any]):
        return AgentRuntimeSettings.model_validate(value).model_dump(mode="json")

    @field_validator("triggers_json")
    @classmethod
    def validate_triggers(cls, value: list[AgentTrigger]):
        if len({trigger.id for trigger in value}) != len(value):
            raise ValueError("触发器标识不能重复")
        return value

    @model_validator(mode="before")
    @classmethod
    def preserve_legacy_model_binding(cls, value):
        """旧 API 只传 model_config_id 时仍视为 Agent 固定模型。"""
        if isinstance(value, dict) and "settings_json" not in value and value.get("model_config_id") is not None:
            value = {**value, "settings_json": {"model_binding": "agent"}}
        return value

    @model_validator(mode="after")
    def require_bound_model(self):
        if self.settings_json.get("model_binding") == "agent" and self.model_config_id is None:
            raise ValueError("选择 Agent 固定模型时必须指定模型配置")
        return self


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
    settings_json: dict[str, Any] | None = None
    triggers_json: list[AgentTrigger] | None = Field(default=None, max_length=30)

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

    @field_validator("settings_json")
    @classmethod
    def validate_optional_settings(cls, value: dict[str, Any] | None):
        return AgentRuntimeSettings.model_validate(value).model_dump(mode="json") if value is not None else value

    @field_validator("triggers_json")
    @classmethod
    def validate_optional_triggers(cls, value: list[AgentTrigger] | None):
        if value is None:
            return value
        if len({trigger.id for trigger in value}) != len(value):
            raise ValueError("触发器标识不能重复")
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
    settings_json: dict[str, Any]
    triggers_json: list[dict[str, Any]]
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ToolDefinitionUpdate(BaseModel):
    description: str = Field(min_length=1, max_length=2000)
    agent_ids: list[int] = Field(default_factory=list, max_length=500)
    parameter_overrides_json: dict[str, dict[str, str]] = Field(default_factory=dict, max_length=100)
    is_enabled: bool = True

    @field_validator("description", mode="before")
    @classmethod
    def strip_description(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("agent_ids")
    @classmethod
    def unique_agent_ids(cls, value: list[int]):
        if len(set(value)) != len(value):
            raise ValueError("Agent 不能重复绑定")
        return value

    @field_validator("parameter_overrides_json")
    @classmethod
    def validate_parameter_overrides(cls, value: dict[str, dict[str, str]]):
        for name, override in value.items():
            if not name or len(name) > 120 or set(override) - {"description", "default"}:
                raise ValueError("参数覆写仅支持参数说明和默认值")
            if any(len(item) > 4000 for item in override.values()):
                raise ValueError("参数说明或默认值过长")
        return value


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    content: str = Field(min_length=1, max_length=100000)
    is_enabled: bool = False
    files_json: dict[str, str] = Field(default_factory=dict, max_length=200)
    mcp_tool_keys_json: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("name", "description", "content", mode="before")
    @classmethod
    def strip_text(cls, value):
        """清理文本。"""
        return value.strip() if isinstance(value, str) else value

    @field_validator("files_json")
    @classmethod
    def validate_files(cls, value: dict[str, str]):
        _validate_skill_files(value)
        return value


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    content: str | None = Field(default=None, min_length=1, max_length=100000)
    is_enabled: bool | None = None
    files_json: dict[str, str] | None = Field(default=None, max_length=200)
    mcp_tool_keys_json: list[str] | None = Field(default=None, max_length=100)

    @field_validator("name", "description", "content", mode="before")
    @classmethod
    def strip_optional_text(cls, value):
        """清理可选文本。"""
        return value.strip() if isinstance(value, str) else value

    @field_validator("files_json")
    @classmethod
    def validate_optional_files(cls, value: dict[str, str] | None):
        if value is not None:
            _validate_skill_files(value)
        return value


class SkillResponse(BaseModel):
    id: int
    key: str
    name: str
    description: str
    content: str
    files_json: dict[str, str]
    mcp_tool_keys_json: list[str]
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


class SkillUsageResponse(BaseModel):
    total_loads: int
    task_count: int
    last_used_at: datetime | None
    agents: list[dict[str, Any]]
    recent_tasks: list[dict[str, Any]]


def _validate_skill_files(value: dict[str, str]) -> None:
    total_size = 0
    for path, content in value.items():
        normalized = path.replace("\\", "/")
        parts = normalized.split("/")
        if normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise ValueError("Skill 文件路径必须是安全的相对路径")
        if normalized == "SKILL.md" and not content.strip():
            raise ValueError("SKILL.md 入口文件不能为空")
        if len(normalized) > 240 or len(content) > 100_000:
            raise ValueError("Skill 文件路径或单文件内容超过限制")
        total_size += len(content.encode("utf-8"))
    if total_size > 1_000_000:
        raise ValueError("Skill 文件总大小不能超过 1 MB")
