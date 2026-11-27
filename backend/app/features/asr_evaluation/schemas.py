"""ASR 音频资产 HTTP 输入合同。

请求 DTO 由 ASR router 校验后交给 service；Wire 字段沿用 snake_case。旧任务、对比与实验 DTO 已随入口退役。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


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