"""统一模型中心请求与响应合同。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelCenterInput(BaseModel):
    """拒绝未声明字段，避免静默保存未生效的供应商参数。"""

    model_config = ConfigDict(extra="forbid")


class ModelProfileInput(ModelCenterInput):
    """一个命名参数方案的首个版本。"""

    name: str = Field(min_length=1, max_length=120)
    values: dict[str, Any] = Field(default_factory=dict)
    definitions: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class ModelResourceCreate(ModelCenterInput):
    """新建平台共享或项目私有模型连接及初始参数方案。"""

    category: Literal["TEXT_GENERATION", "ASR", "DIARIZATION"]
    visibility: Literal["PLATFORM", "PROJECT"]
    project_id: int | None = Field(default=None, gt=0)
    display_name: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=60)
    adapter_key: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=200)
    endpoint: str = Field(min_length=1, max_length=2000)
    credential: str = Field(default="", max_length=8000)
    credential_header: str | None = Field(default=None, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    parameter_schema: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    enabled: bool = True
    initial_profile: ModelProfileInput = Field(default_factory=lambda: ModelProfileInput(name="默认参数"))
    grant_project_ids: list[int] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_scope(self) -> "ModelResourceCreate":
        """保证范围与项目 ID 一致，避免共享模型意外变成项目模型或反向泄露。"""
        if (self.visibility == "PROJECT") != (self.project_id is not None):
            raise ValueError("项目私有模型必须指定 project_id，平台共享模型不能指定项目")
        if self.visibility == "PROJECT" and self.grant_project_ids:
            raise ValueError("项目私有模型不能额外授予其他项目")
        return self


class ModelRevisionInput(ModelCenterInput):
    """为现有资源增加不可变连接修订。"""

    provider: str = Field(min_length=1, max_length=60)
    adapter_key: str = Field(min_length=1, max_length=100)
    model_name: str = Field(min_length=1, max_length=200)
    endpoint: str = Field(min_length=1, max_length=2000)
    credential: str | None = Field(default=None, max_length=8000)
    credential_header: str | None = Field(default=None, max_length=100)
    config: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list, max_length=100)
    parameter_schema: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    enabled: bool = True
    initial_profile: ModelProfileInput | None = None


class ModelProfileCreate(ModelCenterInput):
    """为指定资源创建参数方案的新不可变版本。"""

    revision_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    values: dict[str, Any]
    definitions: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class ModelGrantInput(ModelCenterInput):
    """设置平台共享模型的项目可见授权。"""

    project_ids: list[int] = Field(max_length=500)


class ModelDefaultInput(ModelCenterInput):
    """按用途配置同类别默认模型、参数版本和备用策略。"""

    category: Literal["TEXT_GENERATION", "ASR", "DIARIZATION"]
    purpose: str = Field(min_length=1, max_length=40)
    project_id: int | None = Field(default=None, gt=0)
    resource_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    profile_id: int | None = Field(default=None, gt=0)
    fallback_resource_ids: list[int] = Field(default_factory=list, max_length=3)
    automatic_fallback: bool = False


class ModelAvailableQuery(ModelCenterInput):
    """项目可用模型列表查询参数。"""

    project_id: int = Field(gt=0)
    category: Literal["TEXT_GENERATION", "ASR", "DIARIZATION"] | None = None


class ModelImportPreview(ModelCenterInput):
    """批量导入预检；凭据字段不接受，预检和保存都不触发模型调用。"""

    items: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class ModelDiagnosticInput(ModelCenterInput):
    """明确同意发起可能计费的在线模型请求。"""

    project_id: int = Field(gt=0)
    profile_id: int | None = Field(default=None, gt=0)
    audio_id: int | None = Field(default=None, gt=0)
    confirm_model_call: Literal[True]


class ModelConnectionTestInput(ModelCenterInput):
    """以未保存的文本推理配置发送一次明确触发的在线请求。"""

    visibility: Literal["PLATFORM", "PROJECT"]
    project_id: int | None = Field(default=None, gt=0)
    endpoint: str = Field(min_length=1, max_length=2000)
    model_name: str = Field(min_length=1, max_length=200)
    credential: str = Field(default="", max_length=8000)
    config: dict[str, Any] = Field(default_factory=dict)
    confirm_model_call: Literal[True]

    @model_validator(mode="after")
    def validate_scope(self) -> "ModelConnectionTestInput":
        """平台资源不绑定项目；项目资源测试必须保持所属项目边界。"""
        if (self.visibility == "PROJECT") != (self.project_id is not None):
            raise ValueError("项目私有模型测试必须指定项目，平台共享模型测试不能指定项目")
        return self


__all__ = [
    "ModelAvailableQuery", "ModelConnectionTestInput", "ModelDefaultInput", "ModelDiagnosticInput", "ModelGrantInput",
    "ModelImportPreview", "ModelProfileCreate", "ModelProfileInput", "ModelResourceCreate",
    "ModelRevisionInput",
]
