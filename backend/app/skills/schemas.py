"""Skill 定义、文件树和使用统计的 API 契约。"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


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

class SkillUsageResponse(BaseModel):
    total_loads: int
    task_count: int
    last_used_at: datetime | None
    agents: list[dict[str, Any]]
    recent_tasks: list[dict[str, Any]]

def _validate_skill_files(value: dict[str, str]) -> None:
    """校验 Skill 文件树的相对路径、文本长度和总大小限制。"""
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


class DefinitionVersionResponse(BaseModel):
    """共享的定义版本读取响应。"""

    version: int
    snapshot_json: dict
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
