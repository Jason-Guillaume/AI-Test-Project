"""用户模块：管理员端接口。

路径前缀 /api/v1/users。除 /me 系列外全部要求平台管理员。
/me 系列（注册、登录、改密、我的组织、退出）位于同包的 auth.py，
本文件只保留管理员对全平台账号的分页查询与增删改。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.users.schemas import (
    AdminUserCreate,
    UserListResponse,
    UserResponse,
    UserUpdate,
)
from app.features.users.services.user_service import UserAdminService
from app.shared.auth import get_current_user
from app.shared.database import get_db
from app.shared.errors import forbidden, not_found
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE
from app.shared.roles import is_platform_admin
from app.models.identity import User

router = APIRouter(prefix="/users", tags=["用户管理"])

SERVICE = UserAdminService()


def _require_admin(user: User) -> None:
    """统一的管理员门槛：非平台管理员直接抛 403。"""
    if not is_platform_admin(user):
        raise forbidden("仅管理员可执行该操作")


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    body: AdminUserCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """管理员创建账号；同时创建个人组织与组织成员行。

    Args:
        body: 管理员填写的用户名、初始密码、平台角色与启用状态。
        db: 数据库会话。
        current_user: 触发操作的管理员账号。
    Returns:
        新建用户的完整信息。
    """
    _require_admin(current_user)  # 权限判定：仅平台管理员
    return SERVICE.create_by_admin(db, body, actor=current_user)


@router.get("", response_model=UserListResponse)
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE),
    keyword: str | None = None,
    is_active: bool | None = None,
):
    """分页查询用户，支持按用户名/角色关键字与启用状态过滤。

    Args:
        page: 页码，从 1 开始。
        page_size: 每页条数，受 MAX_PAGE_SIZE 约束。
        keyword: 用户名/平台角色关键字，纯数字时同时按用户 ID 精确匹配。
        is_active: 仅查启用或停用账号。
    Returns:
        {items, total, page, page_size} 信封。
    """
    _require_admin(current_user)
    # 分页参数校验在 Query 声明处完成：ge=1 保证页码与条数非负，le=MAX_PAGE_SIZE 限制上限
    rows, total = SERVICE.page_users(
        db, page=page, page_size=page_size, keyword=keyword, is_active=is_active
    )
    return UserListResponse(items=rows, total=total, page=page, page_size=page_size)


@router.get("/{user_id}", response_model=UserResponse)
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查询单个用户；仅管理员可查他人，普通用户只能查自己。

    Args:
        user_id: 目标用户 ID。
        db: 数据库会话。
        current_user: 当前登录用户。
    Returns:
        目标用户信息。
    """
    # 权限边界：非平台管理员只能看自己，否则 403（而不是 404）以便前端提示无权限
    if not is_platform_admin(current_user) and current_user.id != user_id:
        raise forbidden("无权查看其他用户信息")
    return SERVICE.get_or_404(db, user_id)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user(
    user_id: int,
    body: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """更新用户信息。

    - 平台角色、启用状态仅管理员可改，且修改后会提升 token_version 使旧令牌失效
    - 普通用户只能修改自己的用户名
    - 管理员不能撤销自己的 admin 角色，也不能禁用自己（避免锁死唯一管理员）
    """
    return SERVICE.update_user(db, user_id, body, actor=current_user)  # 具体规则（含 token_version 递增）在 service 层


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除用户；不能删除自己。

    删除动作会把目标用户名下的项目与组织显式交接出去，细节见 service.delete_user。
    """
    _require_admin(current_user)
    SERVICE.delete_user(db, user_id, actor=current_user)
    return None
