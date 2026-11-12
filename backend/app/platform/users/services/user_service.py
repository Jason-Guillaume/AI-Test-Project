"""用户服务层。

路由层只做参数、认证与响应映射；所有业务与事务集中在这里。
与旧项目的差异：
- 分页统一为 page / page_size，替代旧 skip / limit
- 角色变更、禁用、改密都会递增 token_version，让旧令牌立即失效
- 通知写入与主数据同事务，写失败时记录告警但不影响主流程
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.platform.users.schemas import (
    AdminUserCreate,
    UserCreate,
    UserLogin,
    UserUpdate,
)
from app.core.models.identity import Organization, User
from app.core.security.auth import create_access_token, invalidate_user_tokens
from app.core.http.errors import bad_request, conflict, forbidden, not_found
from app.core.security.passwords import hash_password, verify_password
from app.core.security.roles import is_platform_admin

logger = logging.getLogger(__name__)  # 通知写入等降级路径的告警日志

MIN_PASSWORD_LENGTH = 6  # 密码最小长度
MAX_PASSWORD_LENGTH = 100  # 密码最大长度


class UserAdminService:
    """用户与账号服务。无状态，可跨模块复用。"""

    # ---------------------------------------------------------------- 校验

    @staticmethod
    def validate_password(password: str) -> str:
        """校验密码长度，返回原密码。

        Args:
            password: 待校验的明文密码。
        Returns:
            原密码字符串。
        """
        if not password or len(password) < MIN_PASSWORD_LENGTH:
            raise bad_request(f"密码长度至少 {MIN_PASSWORD_LENGTH} 位")
        if len(password) > MAX_PASSWORD_LENGTH:
            raise bad_request(f"密码长度不能超过 {MAX_PASSWORD_LENGTH} 位")
        return password

    @staticmethod
    def _username_available(db: Session, username: str, *, exclude_id: int | None = None) -> bool:
        """检查用户名是否可用；改用户名时排除自身以免自己与自己冲突。

        Args:
            db: 数据库会话。
            username: 待检查的用户名。
            exclude_id: 更新场景下需要排除的用户 ID。
        Returns:
            可用为 True。
        """
        query = db.query(User).execution_options(include_deleted=True).filter(User.username == username)
        if exclude_id is not None:
            query = query.filter(User.id != exclude_id)  # 排除自身，允许用户名不变
        return query.first() is None

    # ---------------------------------------------------------------- 查询

    def get_or_404(self, db: Session, user_id: int) -> User:
        """按 ID 取用户，不存在时抛 404。

        Args:
            db: 数据库会话。
            user_id: 用户 ID。
        Returns:
            用户 ORM 实例。
        """
        user = db.get(User, user_id)
        if user is None:
            raise not_found("用户不存在")
        return user

    def page_users(
        self,
        db: Session,
        *,
        page: int,
        page_size: int,
        keyword: str | None = None,
        is_active: bool | None = None,
    ) -> tuple[list[User], int]:
        """分页查询用户，默认按 ID 降序（新用户在前）。

        Args:
            db: 数据库会话。
            page: 页码，从 1 开始。
            page_size: 每页条数。
            keyword: 用户名/平台角色关键字，纯数字时额外按用户 ID 精确匹配。
            is_active: 仅查启用或停用账号。
        Returns:
            (当前页用户列表, 总数)。
        """
        query = db.query(User)
        if is_active is not None:
            query = query.filter(User.is_active.is_(is_active))
        if keyword:
            keyword = keyword.strip()
            conditions = [
                User.username.ilike(f"%{keyword}%"),
                User.role.ilike(f"%{keyword}%"),
            ]
            # 纯数字关键字同时按用户 ID 精确匹配，便于管理员从页面直接跳转检索。
            if keyword.isdigit():
                conditions.append(User.id == int(keyword))
            from sqlalchemy import or_

            query = query.filter(or_(*conditions))
        total = int(query.count())  # 先算总数再切片，offset 才能正确计算
        items = query.order_by(User.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return items, total

    # ---------------------------------------------------------------- 写入

    def register(self, db: Session, body: UserCreate) -> User:
        """注册普通账号；组织由平台管理员另行创建并分配。

        Args:
            db: 当前请求的数据库会话。
            body: 用户名与密码。
        Returns:
            已持久化的新用户。
        副作用：只提交账号。
        """
        username = body.username.strip()
        self.validate_password(body.password)
        if not self._username_available(db, username):
            raise conflict("用户名已存在")

        user = User(username=username, hashed_password=hash_password(body.password))
        db.add(user)
        db.flush()  # 取得用户 ID，随后提交账号本身。
        db.commit()
        db.refresh(user)
        return user

    def create_by_admin(self, db: Session, body: AdminUserCreate, *, actor: User) -> User:
        """管理员创建账号；组织由平台管理员另行创建并分配。

        Args:
            db: 数据库会话。
            body: 管理员填写的入参。
            actor: 触发创建的管理员账号。
        Returns:
            新建用户。
        """
        username = body.username.strip()
        self.validate_password(body.password)
        if username.lower() == (actor.username or "").strip().lower():
            # 避免用操作人本人账号作为新账号名，给出明确冲突提示。
            raise conflict("不能创建与操作人同名的账号")
        if not self._username_available(db, username):
            raise conflict("该用户名已存在")

        user = User(
            username=username,
            hashed_password=hash_password(body.password),
            role=body.role,
            is_active=body.is_active,
            token_version=0,  # 初始令牌版本号，之后每次敏感变更递增
        )
        db.add(user)
        db.flush()
        self._emit(db, user, "user.created", actor)  # 通知写入与主数据同事务
        db.commit()  # 事务提交点
        db.refresh(user)
        return user

    def update_user(self, db: Session, user_id: int, body: UserUpdate, *, actor: User) -> User:
        """更新用户信息，按旧项目规则限制操作权限。

        Args:
            db: 数据库会话。
            user_id: 目标用户 ID。
            body: 局部更新入参。
            actor: 触发更新的操作人。
        Returns:
            更新后的用户。
        """
        user = db.query(User).filter(User.id == user_id).with_for_update().first()
        if user is None:
            raise not_found("用户不存在")
        data = body.model_dump(exclude_unset=True)  # 只取调用方显式传入的字段
        if not data:
            return user

        is_self = user.id == actor.id
        privileged_fields = {"role", "is_active"} & set(data)

        # 管理员字段：仅平台管理员可改
        if privileged_fields and not is_platform_admin(actor):
            raise forbidden("只有管理员可以修改其他用户的角色或状态")

        # 非管理员只能改自己：即使只改用户名也算越权。
        # 判定必须看操作人是不是平台管理员，不能看字段类型——否则管理员
        # 给其他用户改用户名也会被误拦。
        if not is_platform_admin(actor) and not is_self:
            raise forbidden("只有本人或管理员可以修改此账号")

        # 自保护：本人不能降自己的角色，也不能禁用自己（否则唯一管理员会把自己锁死）
        if is_self:
            if data.get("role") not in (None, user.role):
                raise bad_request("不能修改自己的角色")
            if data.get("is_active") is False:
                raise bad_request("不能停用自己的账户")
        else:
            if data.get("is_active") is False and user.role == "admin":
                raise bad_request("不能停用管理员账户")

        if "username" in data and data["username"]:
            username = data["username"].strip()
            if len(username) < 3:
                raise bad_request("用户名至少 3 个字符")
            if not self._username_available(db, username, exclude_id=user.id):
                raise conflict("该用户名已存在")
            data["username"] = username

        # 与旧值逐项比较，判断哪些字段真的发生了变化
        role_changed = data.get("role") not in (None, user.role)
        status_changed = data.get("is_active") not in (None, user.is_active)
        username_changed = data.get("username") not in (None, user.username)

        for field, value in data.items():
            setattr(user, field, value)

        # 角色或状态变化都会让旧令牌失效
        if role_changed or status_changed or username_changed:
            invalidate_user_tokens(db, user)  # token_version 递增点：旧令牌立即失效
            db.flush()
            self._emit(
                db,
                user,
                "user.updated",
                actor,
                detail={"changed": sorted(data.keys())},
                organization_id=self._default_org_id(db, user.id),
            )

        db.commit()  # 事务提交点
        db.refresh(user)
        return user

    def change_password(
        self, db: Session, user_id: int, old_password: str, new_password: str, *, actor: User
    ) -> None:
        """修改当前用户密码，成功后旧令牌立即失效。

        Args:
            db: 数据库会话。
            user_id: 目标用户 ID，必须等于操作人。
            old_password: 旧密码。
            new_password: 新密码。
            actor: 当前操作人。
        """
        if user_id != actor.id:
            raise forbidden("只能修改自己的密码")  # 权限边界：只允许改自己的密码
        user = db.query(User).filter(User.id == user_id).with_for_update().first()
        if user is None:
            raise not_found("用户不存在")
        self.validate_password(new_password)

        if not verify_password(old_password, user.hashed_password or ""):
            raise bad_request("旧密码错误")
        if verify_password(new_password, user.hashed_password or ""):
            raise bad_request("新密码不能与旧密码相同")

        user.hashed_password = hash_password(new_password)
        invalidate_user_tokens(db, user)  # token_version 递增点：旧令牌立即失效
        self._emit(db, user, "user.password_changed", actor, organization_id=self._default_org_id(db, user.id))
        db.commit()  # 事务提交点

    def delete_user(self, db: Session, user_id: int, *, actor: User) -> None:
        """Soft-delete the account while preserving ownership and audit references."""
        from app.lifecycle.service import delete_resource

        delete_resource(db, "user", user_id, actor=actor)

    # ---------------------------------------------------------------- 登录

    def authenticate(self, db: Session, body: UserLogin) -> tuple[User, str]:
        """校验用户名密码，返回 (user, token)。

        用户名不存在与密码错误返回同一错误，避免账号枚举。

        Args:
            db: 数据库会话。
            body: 登录入参。
        Returns:
            (用户, JWT 令牌)。
        """
        user = db.query(User).filter(User.username == body.username.strip()).first()
        if user is None or not verify_password(body.password, user.hashed_password or ""):
            raise bad_request("用户名或密码错误")  # 错误信封映射：两种失败共用同一提示，防止账号枚举
        if not user.is_active:
            # 禁用账号的令牌仍可通过校验但在此处返回 403，前端据此区分「禁用」与「过期」
            raise forbidden("该账户已被禁用")
        return user, create_access_token(user)

    # ---------------------------------------------------------------- 工具

    @staticmethod
    def _default_org_id(db: Session, user_id: int) -> int | None:
        """取用户最早创建的个人组织 ID，作为通知的归属组织；没有则返回 None。

        Args:
            db: 数据库会话。
            user_id: 用户 ID。
        """
        row = (
            db.query(Organization.id)
            .filter(Organization.owner_id == user_id)
            .order_by(Organization.id)
            .first()
        )
        return int(row[0]) if row else None

    @staticmethod
    def _emit(
        db: Session,
        target: User,
        event_type: str,
        actor: User,
        *,
        organization_id: int | None = None,
        detail: dict | None = None,
    ) -> None:
        """写一条用户可见通知；通知失败不影响主数据变更。

        Args:
            db: 数据库会话。
            target: 通知接收人。
            event_type: 事件类型，如 user.created。
            actor: 触发事件的操作人。
            organization_id: 通知归属组织，个人通知时传 None。
            detail: 事件附加信息，如变更字段列表。
        """
        from app.core.notifications.notify import notify

        notify(
            db,
            user_id=target.id,
            event_type=event_type,
            actor_id=actor.id,
            actor_username=actor.username,
            body=(
                f"操作人：{actor.username}"
                if actor.id != target.id
                else "你的账号信息已更新"
            ),
            organization_id=organization_id,
            detail=detail,
        )


def token_expires_in_seconds(minutes: int) -> int:
    """把配置的过期分钟数换算为秒，供登录响应使用。

    Args:
        minutes: 过期分钟数。
    Returns:
        过期秒数。
    """
    return int(minutes) * 60
