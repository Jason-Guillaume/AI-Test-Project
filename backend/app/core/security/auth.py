"""认证：JWT 签发/校验与当前用户依赖。

沿用旧项目的令牌设计：
- 声明 sub（用户 ID 字符串）、exp（过期时间）、ver（token_version）
- 账号被禁用 → 403「该账户已被禁用」（与旧项目一致，前端据此区分禁用与令牌过期）
- token_version 不一致 → 401「登录失效，请重新登录」
- 令牌指向已删除的用户同样是 401 同一文案，不区分「已删除」与「已撤销」

修改密码、禁用账户、调整平台角色、管理员移除用户时都会递增 token_version，
从而让旧令牌立即失效。
"""

from __future__ import annotations

import jwt
from fastapi import Cookie, Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import ACCESS_TOKEN_EXPIRE_MINUTES, ALGORITHM, settings
from app.core.database.session import get_db
from app.core.http.errors import AUTH_REQUIRED_MESSAGE, forbidden, unauthorized
from app.core.models.identity import User

# tokenUrl 供 Swagger 文档展示，需与 auth 路由的实际挂载点一致：POST /api/v1/login。
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login", auto_error=False)
AUTH_COOKIE_NAME = "access_token"

# 账户被禁用的专用文案，走 403；与令牌失效的 401 文案刻意区分，前端据此提示不同分支。
ACCOUNT_DISABLED_MESSAGE = "该账户已被禁用"
# 令牌失效统一复用 errors 模块的 401 文案，保证全项目口径一致（不区分过期/撤销/用户已删除）。
TOKEN_EXPIRED_MESSAGE = AUTH_REQUIRED_MESSAGE


def create_access_token(user: User) -> str:
    """为已激活用户签发访问令牌，带上 token_version 撤销位。

    Args:
        user: 已通过校验的用户对象（is_active 为真）。

    Returns:
        str: 可直接放进 Authorization: Bearer 头的 JWT 串。

    登录与注册流程唯一调用本函数，不要在其他地方自行拼装声明。
    """
    from datetime import datetime, timedelta, timezone

    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # 声明约定：sub 为用户 ID 的字符串形式（与 FastAPI 文档示例保持一致）；
    # exp 为过期时间；ver 记录签发时的 token_version，校验侧据此比对以实现令牌即时撤销。
    return jwt.encode(
        {
            "sub": str(user.id),
            "exp": expire,
            "ver": int(user.token_version or 0),
        },
        settings.SECRET_KEY,
        algorithm=ALGORITHM,
    )


def invalidate_user_tokens(db: Session, user: User) -> None:
    """递增 token_version，使该用户此前签发的所有令牌立即失效。

    用于：修改密码、禁用账户、调整平台角色、被管理员移除。
    """
    # token_version 递增点：只改内存对象，不自行 flush/commit，
    # 由调用方在同一个事务里一并提交；未提交则撤销不会真正生效。
    user.token_version = int(user.token_version or 0) + 1


def require_admin(user: User, detail: str = "仅管理员可执行该操作") -> None:
    """校验用户为平台管理员，否则抛出 403。"""
    # 延迟导入 roles，避免 shared 内部在模块加载期形成循环依赖。
    from app.core.security.roles import is_platform_admin

    # 权限判定：user.role 不等于 "admin" 一律拒绝，且不区分「非管理员」与「角色已变更」。
    if not is_platform_admin(user):
        raise forbidden(detail)


def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    cookie_token: str | None = Cookie(default=None, alias=AUTH_COOKIE_NAME),
    db: Session = Depends(get_db),
) -> User:
    """解析 HttpOnly Cookie 或兼容的 Bearer JWT，返回当前登录用户。

    Args:
        request: 用于区分 Cookie 鉴权并校验写请求来源。
        token: OAuth2PasswordBearer 解出的 Bearer 令牌；兼容旧 API 客户端。
        cookie_token: 浏览器认证 Cookie 中的令牌。
        db: 请求级数据库会话，用于按 sub 反查用户。

    Returns:
        User: 当前登录用户，调用方可安全使用其 id / role / is_active 等字段。
    """
    # 浏览器登录优先使用 HttpOnly Cookie；Bearer 仅为已有 API 客户端保留兼容。
    uses_cookie = bool(cookie_token)
    selected_token = cookie_token if uses_cookie else token
    if uses_cookie and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin", "").rstrip("/")
        allowed_origins = {item.strip().rstrip("/") for item in settings.CORS_ORIGINS}
        # Cookie 会被浏览器自动附带，写请求必须来自显式信任的前端 Origin，防止跨站伪造。
        if not origin or origin not in allowed_origins:
            raise forbidden("请求来源无效")
    if not selected_token:
        raise unauthorized(TOKEN_EXPIRED_MESSAGE)
    try:
        # JWT 校验必须显式传入 algorithms，避免算法混淆与把算法名误当成 audience。
        payload = jwt.decode(selected_token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
        claimed_version = payload.get("ver", 0)
    except (jwt.PyJWTError, TypeError, ValueError):
        raise unauthorized(TOKEN_EXPIRED_MESSAGE)

    user = db.get(User, user_id)
    if user is None:
        # 用户被删除后其令牌同样走统一 401，不暴露「该用户存在过」。
        raise unauthorized(TOKEN_EXPIRED_MESSAGE)
    if not user.is_active:
        raise forbidden(ACCOUNT_DISABLED_MESSAGE)
    try:
        valid_version = int(claimed_version) == int(user.token_version or 0)
    except (TypeError, ValueError):
        valid_version = False
    if not valid_version:
        raise unauthorized(TOKEN_EXPIRED_MESSAGE)
    return user


def require_platform_admin(user: User = Depends(get_current_user)) -> User:
    """路由级依赖：仅平台管理员可访问；通过时返回该用户对象。

    通过 Depends(require_platform_admin) 挂在需要平台管理员身份的路由上，
    内部复用于 require_admin 的判定，不重复实现权限规则。
    """
    require_admin(user)
    return user


def require_active_user(user: User) -> User:
    """显式校验账户可用（供需要额外状态检查的服务复用）。

    轻量版的账户可用性检查：不改令牌、不递增 token_version，
    仅在调用点需要额外确认状态时使用。
    """
    if not user.is_active:
        raise forbidden(ACCOUNT_DISABLED_MESSAGE)
    return user
