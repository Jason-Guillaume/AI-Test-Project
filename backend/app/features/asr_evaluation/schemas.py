"""ASR 评测 HTTP 输入合同。

请求 DTO 由 ASR router 校验后交给 service；Wire 字段沿用 snake_case。模板只接收 JSON 对象，
凭据单独通过一次性输入传递，不从任何响应 DTO 回传。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class AsrInput(BaseModel):
    """拒绝未声明字段，避免客户端误以为任意配置已经生效。"""

    model_config = ConfigDict(extra="forbid")


class AudioItemInput(AsrInput):
    """单条音频链接导入字段。"""

    name: str = Field(min_length=1, max_length=200)
    url: HttpUrl
    duration_seconds: int | None = Field(default=None, ge=1, le=86_400)
    tags: list[str] = Field(default_factory=list, max_length=30)


class AudioCreate(AsrInput):
    """创建单条项目音频资源。"""

    project_id: int = Field(gt=0)
    audio: AudioItemInput


class AudioUpdate(AsrInput):
    """更新音频名称、URL 或已知时长；未提交字段保持原值。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    url: HttpUrl | None = None
    duration_seconds: int | None = Field(default=None, ge=1, le=86_400)


class AudioImport(AsrInput):
    """批量导入已有音频链接。"""

    project_id: int = Field(gt=0)
    items: list[AudioItemInput] = Field(min_length=1, max_length=200)


class ConnectionCreate(AsrInput):
    """创建一个通用 JSON HTTP ASR 连接版本。"""

    project_id: int = Field(gt=0)
    task_type: Literal["TRANSCRIPTION", "DIARIZATION"] = "TRANSCRIPTION"
    name: str = Field(min_length=1, max_length=120)
    role: Literal["TEST", "REFERENCE"] | None = "TEST"
    provider_id: str = Field(default="generic-json", min_length=1, max_length=80)
    model_id: str = Field(min_length=1, max_length=160)
    endpoint: HttpUrl
    method: Literal["POST"] = "POST"
    headers: dict[str, str] = Field(default_factory=dict, max_length=30)
    request_template: dict[str, Any]
    response_mapping: dict[str, Any]
    parameter_definitions: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    async_config: dict[str, Any] | None = None
    timeout_seconds: int = Field(default=180, ge=1, le=1800)
    max_response_bytes: int = Field(default=8_000_000, ge=1024, le=20_000_000)
    secret: str | None = Field(default=None, max_length=8000)
    secret_header: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_task_role(self) -> "ConnectionCreate":
        """保持任务能力与三方转写角色正交，防止说话人连接被计作第四家 ASR。"""
        if self.task_type == "TRANSCRIPTION" and self.role is None:
            raise ValueError("转写连接必须选择待测或参考角色")
        if self.task_type == "DIARIZATION" and self.role is not None:
            raise ValueError("说话人处理连接不设置三方转写角色")
        return self


class ParameterDefinition(AsrInput):
    """一个可供参数表单及建议校验使用的字段定义。"""

    path: str = Field(min_length=1, max_length=300)
    display_name: str = Field(min_length=1, max_length=120)
    value_type: Literal["string", "integer", "number", "boolean", "object", "array"]
    minimum: float | None = None
    maximum: float | None = None
    choices: list[Any] | None = None
    description: str = Field(default="", max_length=1000)
    source: str = Field(default="接口提供方说明", max_length=200)


class ParameterSetCreate(AsrInput):
    """创建待测模型参数方案的一个版本。"""

    project_id: int = Field(gt=0)
    connection_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    parameters: dict[str, Any]
    definitions: list[ParameterDefinition] = Field(default_factory=list, max_length=200)


class ModelTaskSlotInput(AsrInput):
    """把某模型修订与参数方案绑定到单个任务角色，而不写入模型永久属性。"""

    slot: Literal["TEST", "REFERENCE_A", "REFERENCE_B", "DIARIZATION"]
    resource_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    profile_id: int = Field(gt=0)


class JobCreate(AsrInput):
    """创建一批持久化三方评测任务。"""

    project_id: int = Field(gt=0)
    audio_ids: list[int] = Field(min_length=1, max_length=200)
    connection_ids: list[int] | None = Field(default=None, min_length=3, max_length=3)
    parameter_set_id: int | None = Field(default=None, gt=0)
    model_slots: list[ModelTaskSlotInput] | None = Field(default=None, min_length=3, max_length=4)

    @model_validator(mode="after")
    def validate_slot_selection(self) -> "JobCreate":
        """保留旧请求兼容，同时要求新任务提供三个 ASR 槽位及其独立参数方案。"""
        if self.model_slots is None:
            if self.connection_ids is None or self.parameter_set_id is None:
                raise ValueError("任务必须提供旧配置或模型槽位")
            return self
        slots = [item.slot for item in self.model_slots]
        if len(slots) != len(set(slots)) or not {"TEST", "REFERENCE_A", "REFERENCE_B"}.issubset(slots):
            raise ValueError("模型槽位必须包含 TEST、REFERENCE_A 和 REFERENCE_B，且不能重复")
        return self


class ConnectionCheck(AsrInput):
    """以短后台任务调试一个已配置连接。"""

    audio_id: int = Field(gt=0)
    parameter_set_id: int | None = Field(default=None, gt=0)


class ScheduleCreate(AsrInput):
    """创建一次性或每日评测计划。"""

    project_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=160)
    audio_ids: list[int] = Field(min_length=1, max_length=200)
    connection_ids: list[int] | None = Field(default=None, min_length=3, max_length=3)
    parameter_set_id: int | None = Field(default=None, gt=0)
    model_slots: list[ModelTaskSlotInput] | None = Field(default=None, min_length=3, max_length=4)
    schedule_type: Literal["ONCE", "DAILY"]
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=80)
    local_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    scheduled_at: str | None = None

    @model_validator(mode="after")
    def validate_slot_selection(self) -> "ScheduleCreate":
        """夜间计划同样允许按任务槽位选择模型及各自参数版本。"""
        if self.model_slots is None:
            if self.connection_ids is None or self.parameter_set_id is None:
                raise ValueError("计划必须提供旧配置或模型槽位")
            return self
        slots = [item.slot for item in self.model_slots]
        if len(slots) != len(set(slots)) or not {"TEST", "REFERENCE_A", "REFERENCE_B"}.issubset(slots):
            raise ValueError("夜间计划必须包含 TEST、REFERENCE_A 和 REFERENCE_B，且不能重复")
        return self


class ScheduleUpdate(AsrInput):
    """启用或暂停一个项目夜间计划。"""

    enabled: bool


class ReviewInput(AsrInput):
    """带乐观锁版本的人工确认或暂无法确认操作。"""

    expected_version: int = Field(ge=0)
    review_status: Literal["CONFIRMED", "UNRESOLVED"]
    confirmed_text: str | None = Field(default=None, max_length=100_000)
    include_reference_sample: bool = False


class ExperimentCreate(AsrInput):
    """创建独立候选参数草稿，不触碰基线方案。"""

    comparison_id: int = Field(gt=0)
    candidate_parameters: dict[str, Any]
    change_summary: str = Field(min_length=1, max_length=2000)
    reuse_reference_results: bool = False


class DiarizationRunCreate(AsrInput):
    """固定一个音频版本、说话人模型修订与参数方案，独立排队分析。"""

    connection_id: int | None = Field(default=None, gt=0)
    parameters: dict[str, Any] | None = None
    resource_id: int | None = Field(default=None, gt=0)
    revision_id: int | None = Field(default=None, gt=0)
    profile_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_model_selection(self) -> "DiarizationRunCreate":
        """新合同固定资源、修订和方案；旧连接字段作为过渡兼容读取。"""
        canonical = (self.resource_id is not None, self.revision_id is not None, self.profile_id is not None)
        if any(canonical) and not all(canonical):
            raise ValueError("说话人模型选择必须同时指定资源、修订和参数方案")
        if not all(canonical) and self.connection_id is None:
            raise ValueError("必须选择统一模型资源或旧说话人连接")
        if all(canonical) and self.connection_id is not None:
            raise ValueError("不能同时提交统一模型资源与旧连接 ID")
        return self


class SpeakerFusionCreate(AsrInput):
    """选择同一音频版本的说话人结果，为指定 ASR 运行生成关联版本。"""

    diarization_result_id: int = Field(gt=0)


class SpeakerReviewInput(AsrInput):
    """以乐观锁确认一个转写范围的说话人归属或未知状态。"""

    expected_version: int = Field(ge=0)
    review_status: Literal["CONFIRMED", "UNRESOLVED"]
    speaker_id: int | None = Field(default=None, gt=0)


class SpeakerNameUpdate(AsrInput):
    """更新本次说话人结果内的显示名，保留模型原始标签与审计记录。"""

    display_name: str = Field(min_length=1, max_length=120)


class ProcessingRetryInput(AsrInput):
    """仅指定失败的处理运行重试，不重新创建三方转写运行。"""

    pass
