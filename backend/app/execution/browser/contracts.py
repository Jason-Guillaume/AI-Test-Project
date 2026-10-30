"""唯一的受控浏览器步骤与定位器契约。"""

from __future__ import annotations

import base64
import re
from typing import Literal

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
