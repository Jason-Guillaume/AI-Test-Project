"""内置工具管理接口的 API 契约。"""
from __future__ import annotations
from pydantic import BaseModel, Field, field_validator


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
