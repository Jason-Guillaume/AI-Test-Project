"""HTTP contracts for the dedicated FunASR analysis and tuning workflow."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FunAsrInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FunAsrBindingCreate(FunAsrInput):
    project_id: int = Field(gt=0)
    api_interface_id: int = Field(gt=0)
    environment_name: str = Field(min_length=1, max_length=100)
    response_mapping: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=180, ge=1, le=1800)
    max_response_bytes: int = Field(default=8_000_000, ge=1024, le=20_000_000)
    credential: str | None = Field(default=None, max_length=8000)
    credential_header: str | None = Field(default=None, max_length=100)


class FunAsrBindingUpdate(FunAsrInput):
    response_mapping: dict[str, Any]
    response_sample: Any


class FunAsrNormalizePreview(FunAsrInput):
    document: Any
    mapping: dict[str, Any]
    source: Literal["ground_truth", "recognition"] = "recognition"
    audio_version_id: int = Field(default=1, ge=1)


class FunAsrGroundTruthCreate(FunAsrInput):
    document: Any
    mapping: dict[str, Any]


class FunAsrTuningCreate(FunAsrInput):
    project_id: int = Field(gt=0)
    binding_id: int = Field(gt=0)
    model_config_id: int = Field(gt=0)
    audio_ids: list[int] = Field(min_length=1, max_length=200)
    parameters: dict[str, Any]
    allowed_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)
    mode: Literal["ANALYZE", "AUTO_TUNE"] = "AUTO_TUNE"
    max_rounds: int = Field(default=8, ge=1, le=100)
    max_asr_requests: int = Field(ge=1, le=20_000)
    max_ai_calls: int = Field(default=8, ge=1, le=100)
    no_improvement_limit: int = Field(default=3, ge=1, le=20)
    failed_items_limit: int = Field(default=1, ge=0, le=200)
    target_micro_cer: float | None = Field(default=None, ge=0, le=5)
    min_improvement: float = Field(default=0.001, ge=0, le=1)
    max_sample_degradation: float = Field(default=0.05, ge=0, le=5)
    window_enabled: bool = False
    night_start: str = Field(default="22:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    night_end: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_limits(self) -> "FunAsrTuningCreate":
        if self.window_enabled and self.night_start == self.night_end:
            raise ValueError("夜间窗口起止时间必须不同")
        if self.allowed_parameters and set(self.allowed_parameters) - {"/" + key for key in self.parameters}:
            raise ValueError("搜索范围只能指定基线已有的参数字段")
        return self
