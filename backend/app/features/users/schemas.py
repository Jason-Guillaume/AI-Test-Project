"""用户模块：契约定义。

与旧项目保持一致的校验规则：
- 用户名 3–50 字符
- 新密码 12–100 字符（旧 PasswordChange.new_password 同为 min 12）
- 旧密码 6–30 字符（旧 PasswordChange.old_password 为 min 6 / max 30）
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.shared.pagination import DEFAULT_PAGE_SIZE

# 平台角色三选一：admin 平台管理员 / test 测试工程师 / dev 开发工程师
PlatformRole = Literal["admin", "test", "dev"]

# 平台业务角色说明，供前端下拉与提示复用。
ROLE_LABELS: dict[str, str] = {"admin": "平台管理员", "test": "测试工程师", "dev": "开发工程师"}


def _strip(value):
    """字符串字段进入校验前统一去首尾空白；非字符串原样返回。"""
    return value.strip() if isinstance(value, str) else value


class UserBase(BaseModel):
    """用户共有字段。"""

    username: str = Field(..., min_length=3, max_length=50, description="用户名")  # 用户名，3–50 字符

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, value):
        """用户名在进入长度校验前先 strip，避免仅含空格的输入绕过 min_length。"""
        return _strip(value)


class UserCreate(UserBase):
    """注册入参。

    图形验证码为必填：注册前必须通过一次 ``GET /captcha`` 拿到的 challenge，
    后端在 service 层用一次性 ``verify_challenge`` 校验。
    """

    password: str = Field(..., min_length=6, max_length=100, description="密码")  # 初始密码
    captcha_id: str = Field(
        ..., min_length=1, max_length=64, description="验证码 challenge_id"
    )
    captcha_code: str = Field(
        ..., min_length=4, max_length=8, description="用户输入的验证码"
    )


class AdminUserCreate(BaseModel):
    """管理员创建账号入参。

    与注册同为 6 位最小长度，避免管理员发出初始密码后用户因校验不一致无法改密。
    """

    username: str = Field(..., min_length=3, max_length=50, description="用户名")  # 新账号用户名
    password: str = Field(..., min_length=6, max_length=100, description="初始密码")  # 管理员设定的初始密码
    role: PlatformRole = "test"  # 平台角色，默认测试工程师
    is_active: bool = True  # 账号是否立即可用

    @field_validator("username", mode="before")
    @classmethod
    def strip_username(cls, value):
        """同 UserBase：进入校验前先去掉首尾空白。"""
        return _strip(value)


class UserLogin(BaseModel):
    """登录入参。"""

    username: str = Field(..., min_length=1, max_length=50)  # 登录用户名，只要求非空
    password: str = Field(..., min_length=1, max_length=100)  # 登录密码，长度在业务层校验


class UserUpdate(BaseModel):
    """用户信息更新入参（局部）。"""

    username: str | None = Field(  # 用户名
        None, min_length=3, max_length=50, description="用户名"
    )
    role: PlatformRole | None = Field(None, description="平台角色：admin/test/dev")  # 平台角色
    is_active: bool | None = Field(None, description="是否激活")  # 是否激活

    @field_validator("username", mode="before")
    @classmethod
    def strip_optional_username(cls, value):
        """可空字段的 strip；None 由 _strip 原样返回。"""
        return _strip(value)


class UserResponse(UserBase):
    """返回给前端的用户信息，不包含密码。"""

    id: int  # 用户 ID
    role: PlatformRole  # 平台角色
    is_active: bool  # 是否激活
    created_at: datetime  # 账号创建时间
    updated_at: datetime  # 最近更新时间

    model_config = ConfigDict(from_attributes=True)  # 允许直接从 ORM 实例取值


class PasswordChange(BaseModel):
    """修改当前用户密码入参。"""

    old_password: str = Field(..., min_length=6, max_length=30, description="旧密码")  # 旧密码
    new_password: str = Field(..., min_length=12, max_length=100, description="新密码")  # 新密码


class TokenResponse(BaseModel):
    """登录成功响应。"""

    access_token: str  # JWT 访问令牌
    token_type: str = "bearer"  # 令牌类型，固定 bearer
    expires_in: int = Field(..., description="令牌有效期（秒）")  # 有效期秒数
    user: UserResponse  # 登录用户的完整信息


class UserListResponse(BaseModel):
    """分页用户列表响应。"""

    total: int  # 满足过滤条件的总数
    items: list[UserResponse]  # 当前页用户
    page: int = 1  # 当前页码
    page_size: int = DEFAULT_PAGE_SIZE  # 每页条数


__all__ = [
    "AdminUserCreate",
    "PasswordChange",
    "PlatformRole",
    "ROLE_LABELS",
    "TokenResponse",
    "UserBase",
    "UserCreate",
    "UserListResponse",
    "UserLogin",
    "UserResponse",
    "UserUpdate",
]
