"""Agent 定义、触发器与历史版本的 API 契约。"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.agents.workflows.catalog import WORKFLOW_TEMPLATES
from app.skills.schemas import DefinitionVersionResponse


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

