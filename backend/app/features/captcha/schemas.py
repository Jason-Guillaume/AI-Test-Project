"""图形验证码模块：契约定义。

只放请求/响应 Pydantic 模型，不含任何业务逻辑；service 与 router 共用这里的类型。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CaptchaResponse(BaseModel):
    """验证码签发响应。

    Attributes:
        challenge_id: 唯一标识，注册时回传以关联对应校验码；一次性使用。
        image_base64: data:image/png;base64,... 完整 URI，前端直接作为 <img src> 使用。
        expires_in: 图片有效期（秒），前端可据此提示「即将过期」或触发自动刷新。
    """

    challenge_id: str = Field(..., description="验证码唯一标识")
    image_base64: str = Field(..., description="data:image/png;base64 完整 URI")
    expires_in: int = Field(..., description="有效期（秒）")


__all__ = ["CaptchaResponse"]
