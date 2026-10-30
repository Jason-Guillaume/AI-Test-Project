"""跨模块依赖注入组合。

集中放置需要被多个模块共用的 Depends 组合，避免每个 feature 重复装配
「数据库会话 + 当前用户」。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.database.session import get_db
from app.core.http.errors import forbidden
from app.core.models.identity import User
from app.core.security.auth import get_current_user
from app.core.security.roles import is_platform_admin

DB = Annotated[Session, Depends(get_db)]
# Current：拿到即代表「令牌有效、账户启用、token_version 未过期」的当前用户。
Current = Annotated[User, Depends(get_current_user)]


def require_platform_admin(user: User) -> None:
    """声明式依赖：仅平台管理员可通过。"""
    # 平台管理员门槛：作为 Depends(require_platform_admin) 单独挂在路由上。
    if not is_platform_admin(user):
        raise forbidden("仅管理员可执行该操作")


__all__ = [
    "Current",
    "DB",
    "get_current_user",
    "get_db",
    "require_platform_admin",
]
