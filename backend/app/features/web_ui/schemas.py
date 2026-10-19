"""Web UI 请求契约；只允许固定操作和定位策略，未知字段直接拒绝，脚本不进入执行面。"""
from __future__ import annotations
import base64
import re
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator


class StrictModel(BaseModel):
    """拒绝额外字段，避免脚本或不受支持配置静默进入数据库。"""
    model_config = ConfigDict(extra="forbid")


class Locator(StrictModel):
    """优先稳定的语义定位器，CSS/XPath 仅作为显式兜底。"""
    strategy: Literal["TEST_ID", "ROLE", "LABEL", "TEXT", "CSS", "XPATH"] = "TEST_ID"
    value: str = Field(min_length=1, max_length=1000)
    name: str | None = Field(None, max_length=200)
    exact: bool = True


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


class Upload(StrictModel):
    """内存上传，禁止读取服务器任意路径。"""
    name: str = Field(min_length=1, max_length=120, pattern=r"^[^/\\]+$")
    mime_type: str = Field(default="application/octet-stream", max_length=100)
    content_base64: str = Field(max_length=1400000)

    @model_validator(mode="after")
    def check_content(self):
        """严格校验 Base64 和单文件 1MiB 限额。"""
        if len(base64.b64decode(self.content_base64, validate=True)) > 1048576:
            raise ValueError("上传文件不能超过 1MiB")
        return self


class WebStep(StrictModel):
    """白名单操作；所有外部值均作为数据，绝不 eval/exec。"""
    name: str = Field(min_length=1, max_length=200)
    operation: Literal["NAVIGATE", "CLICK", "FILL", "SELECT", "UPLOAD", "WAIT", "ASSERT"]
    locator: Locator | None = None
    page_object_id: int | None = Field(None, ge=1)
    element_key: str | None = Field(None, max_length=80)
    value: str | None = Field(None, max_length=5000)
    timeout_ms: int | None = Field(None, ge=100, le=60000)
    wait_state: Literal["visible", "hidden", "attached", "detached"] = "visible"
    assertion: Literal["TEXT", "VALUE", "VISIBLE", "COUNT", "URL", "TITLE"] = "TEXT"
    operator: Literal["EQ", "NE", "CONTAINS", "GT", "GE", "LT", "LE"] = "EQ"
    expected: str | None = Field(None, max_length=5000)
    sensitive: bool = False
    upload: Upload | None = None
    output_variable: str | None = Field(None, pattern=r"^[A-Za-z][A-Za-z0-9_]{0,79}$")

    @model_validator(mode="after")
    def check_operation(self, info: ValidationInfo):
        """按操作检查必填配置，敏感输入只能引用加密账号或运行时变量。"""
        needs_locator = self.operation not in ("NAVIGATE",) and not (
            self.operation == "ASSERT" and self.assertion in ("URL", "TITLE")
        )
        if needs_locator and self.locator is None and not (self.page_object_id and self.element_key):
            raise ValueError("该操作需要定位器或页面元素引用")
        if self.operation in ("NAVIGATE", "FILL", "SELECT") and self.value is None:
            raise ValueError("该操作需要 value")
        if self.operation == "UPLOAD" and self.upload is None:
            raise ValueError("UPLOAD 需要内存文件内容")
        if self.operation == "NAVIGATE" and re.match(r"^(javascript|file|data|chrome|about):", self.value or "", re.I):
            raise ValueError("仅允许 HTTP/HTTPS 页面")
        if self.operation == "FILL" and self.locator and re.search(r"password|passwd|pwd|secret|token|密码|口令", self.locator.model_dump_json(), re.I):
            self.sensitive = True
        if not (info.context or {}).get("resolved") and self.sensitive and self.value and not re.fullmatch(r"\$\{(?:data|runtime|fixture)\.[A-Za-z0-9_.]+\}", self.value):
            raise ValueError("敏感值必须引用加密账号 data.auth_* 或运行时变量")
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
