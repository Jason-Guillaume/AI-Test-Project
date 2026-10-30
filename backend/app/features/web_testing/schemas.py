"""Web UI 请求契约；只允许固定操作和定位策略，未知字段直接拒绝，脚本不进入执行面。"""
from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import Field, model_validator
from app.execution.browser.contracts import Locator, StrictModel, Upload, WebStep


class Element(StrictModel):
    """页面对象的可复用命名元素。"""
    key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,79}$")
    locator: Locator


class PageInput(StrictModel):
    """页面及其元素整体保存，revision 用于并发更新检查。"""
    name: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=2000)
    elements: list[Element] = Field(default_factory=list, max_length=100)
    revision: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def unique_keys(self):
        """相同 key 不允许歧义定位。"""
        if len({e.key for e in self.elements}) != len(self.elements):
            raise ValueError("页面元素 key 不可重复")
        return self


class CaseInput(StrictModel):
    """Web 用例整体保存到 TestCase/TestStep，数组顺序就是执行顺序。"""
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    auth_profile_id: int | None = Field(None, ge=1)
    timeout_ms: int = Field(default=30000, ge=100, le=60000)
    total_timeout_ms: int = Field(default=120000, ge=1000, le=600000)
    steps: list[WebStep] = Field(min_length=1, max_length=100)
    revision: int | None = Field(None, ge=1)


class AuthInput(StrictModel):
    """只写登录凭据、Cookie/LocalStorage/JWT 或人工扫码后导入的 Playwright storage_state。"""
    name: str = Field(min_length=1, max_length=200)
    environment_id: int = Field(ge=1)
    username: str | None = Field(None, max_length=200)
    password: str | None = Field(None, max_length=1000)
    jwt: str | None = Field(None, max_length=10000)
    jwt_storage_key: str = Field(default="access_token", min_length=1, max_length=100)
    storage_state: dict[str, Any] = Field(default_factory=lambda: {"cookies": [], "origins": []})
    expires_at: datetime


class ConfirmInput(StrictModel):
    """人工确认当前 revision；Agent 工具没有确认入口。"""
    revision: int = Field(ge=1)


class DebugInput(StrictModel):
    """调试仅选择平台环境，不接受临时脚本或任意 URL。"""
    environment_id: int = Field(ge=1)


class GenerateInput(StrictModel):
    """生成时只送业务流程和页面对象；凭据不进入模型上下文。"""
    instruction: str = Field(min_length=1, max_length=4000)
    flow_id: int | None = Field(None, ge=1)
    page_object_ids: list[int] = Field(default_factory=list, max_length=20)


class BindingInput(StrictModel):
    """为业务动作显式选择默认 WEB 用例。"""
    web_case_id: int = Field(ge=1)


class PageResponse(PageInput):
    """页面对象只读字段。"""
    id: int
    project_id: int
    revision: int


class CaseResponse(CaseInput):
    """结构化用例与当前确认状态，不含密文存储细节。"""
    id: int
    project_id: int
    revision: int
    source_type: str
    confirmed: bool


class AuthResponse(StrictModel):
    """认证只读契约：不允许凭据明文字段进入响应。"""
    id: int
    project_id: int
    environment_id: int
    name: str
    configured: bool
    expires_at: datetime


class PromoteInput(StrictModel):
    """把智能体沙箱会话里已接受的步骤提升为正式 Web 用例。

    提升只产出**未确认**草稿（confirmed=false）：正式执行仍需走人工确认门禁。
    名称与描述可省略，省略时按会话 ID 自动生成，便于批量提升。
    """
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    timeout_ms: int = Field(default=30000, ge=100, le=60000)
    total_timeout_ms: int = Field(default=120000, ge=1000, le=600000)


class SessionStartInput(StrictModel):
    """启动受控浏览器会话：选定环境、登录态与目标页。"""
    environment_id: int = Field(ge=1)
    auth_profile_id: int | None = Field(None, ge=1)
    target_page_path: str = Field(default="", max_length=2000)
    step_budget: int = Field(default=20, ge=1, le=100)


class SessionResponse(StrictModel):
    """会话元信息；不包含任何凭据或浏览器句柄。"""
    id: int
    project_id: int
    environment_id: int
    auth_profile_id: int | None
    base_url: str
    target_page_path: str
    status: str
    status_reason: str | None = None
    step_budget: int
    step_count: int = 0
    created_at: datetime | None = None


class SessionObserveResponse(StrictModel):
    """页面观测结果：脱敏语义树与遮罩截图，可直接供 LLM 或前端使用。"""
    url: str
    title: str
    accessibility_tree: str
    screenshot_b64: str
