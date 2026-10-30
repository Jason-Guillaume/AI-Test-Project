"""飞书通知渠道与发送记录契约（Pydantic v2）。

安全红线（§十五/§三一）：webhook_url / secret 只写不读——创建/更新时接收明文并加密入库，
响应中**永不**返回明文，仅返回 webhook_configured（布尔）与 webhook_masked（脱敏 URL）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 渠道类型与发送条件 / 状态字面量（与 reports.schemas 同义，本模块为通知概念的正典）。
ChannelType = Literal["FEISHU_WEBHOOK"]
NotifyCondition = Literal["ALWAYS", "ONLY_FAILED", "ONLY_HIGH_RISK"]
NotifyStatus = Literal["PENDING", "SUCCESS", "FAILED"]


# --------------------------------------------------------------------------- 渠道：请求


class ChannelCreateRequest(BaseModel):
    """创建飞书通知渠道（webhook_url / secret 明文传入，加密入库）。"""

    name: str = Field(..., min_length=1, max_length=100)
    channel_type: ChannelType = "FEISHU_WEBHOOK"
    webhook_url: str = Field(..., min_length=1, description="飞书 webhook URL（明文，仅写入，加密存储）")
    secret: str | None = Field(None, description="飞书签名密钥（明文，仅写入，加密存储）；不填则不签名")
    enabled: bool = True
    notify_condition: NotifyCondition = "ALWAYS"
    keyword: str | None = Field(None, description="飞书关键词校验（可选，明文存储）")


class ChannelUpdateRequest(BaseModel):
    """更新渠道；webhook_url / secret 留空表示不变，提供则覆盖加密。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    webhook_url: str | None = Field(None, description="留空不变；提供则覆盖加密")
    secret: str | None = Field(None, description="留空不变；提供则覆盖加密（传空串表示清除签名）")
    enabled: bool | None = None
    notify_condition: NotifyCondition | None = None
    keyword: str | None = None


class SendTestRequest(BaseModel):
    """渠道连通性测试（发送一条测试卡片，不关联报告）。"""

    pass


class NotifyReportRequest(BaseModel):
    """手动触发某报告的飞书通知（指定渠道）。Agent 闭环另有节点触发。

    channel_id 可省略：省略时取项目首个启用渠道，均无则跳过（skipped=true），
    与 Agent 路径保持一致的「无渠道不发」安全默认，而不是抛 422。
    """

    channel_id: int | None = Field(None, ge=1)


# --------------------------------------------------------------------------- 渠道：响应（永不回吐 webhook 明文）


class ChannelResponse(BaseModel):
    """渠道对外响应：只回脱敏信息，webhook_url / secret 绝不在响应中。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    channel_type: str
    enabled: bool
    notify_condition: str
    webhook_configured: bool = Field(False, description="是否已配置 webhook URL")
    webhook_masked: str = Field("", description="脱敏 webhook URL，如 https://open.feishu.cn/...****")
    keyword: str | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class ChannelListResponse(BaseModel):
    """渠道列表分页响应（与分页约定 {items,total,page,page_size} 一致）。"""

    items: list[ChannelResponse]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- 发送记录：响应


class NotificationRecordResponse(BaseModel):
    """发送审计记录响应。不含 request_snapshot 中的卡片原文（保留服务端审计，§三一）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    channel_id: int
    report_id: int | None = None
    status: str
    error_message: str | None = None
    sent_at: datetime | None = None
    created_at: datetime


class NotificationRecordListResponse(BaseModel):
    """发送记录列表分页响应。"""

    items: list[NotificationRecordResponse]
    total: int
    page: int
    page_size: int


class SendResultResponse(BaseModel):
    """触发发送（手动 / 连通性测试）的即时结果。"""

    record_id: int | None = None
    status: NotifyStatus
    error_message: str | None = None
    skipped: bool = Field(False, description="因通知条件不满足而跳过（未发送）")
