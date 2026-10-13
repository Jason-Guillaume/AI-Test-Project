"""图形验证码路由。

路径前缀 /api/v1/captcha。签发接口不要求登录：注册等场景下用户尚未拿到 token，
但需要在提交前完成一次校验。

限流：按 IP 计数，命中阈值得到 429，与其他 auth 端点共用同一限流模块。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.features.captcha.schemas import CaptchaResponse
from app.features.captcha.service import generate_challenge
from app.shared.rate_limit import enforce_auth_rate_limit

router = APIRouter(tags=["验证码"])


@router.get("/captcha", response_model=CaptchaResponse)
def issue_captcha(request: Request):
    """签发一张图形验证码。

    Args:
        request: 用于取客户端地址做限流。

    Returns:
        CaptchaResponse: 含 challenge_id、data:image/png;base64 URI 与有效期。
    """
    enforce_auth_rate_limit(request, "captcha")  # 限流：按 captcha 桶，按 IP 计数
    challenge_id, image_uri, expires_in = generate_challenge()
    return CaptchaResponse(
        challenge_id=challenge_id,
        image_base64=image_uri,
        expires_in=expires_in,
    )
