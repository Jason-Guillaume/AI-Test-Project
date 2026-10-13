"""初始化管理员脚本。

状态：已弃用（legacy）。当前没有任何代码引用本模块，真正的初始化入口是
仓库根目录下的 ``scripts/seed_admin.py``（建库 + 迁移 + 种子数据）。
本文件仅为兼容旧的 ``python -m app.scripts.seed_admin`` 调用方式而保留，
若要调整管理员初始化逻辑，请优先修改 scripts/seed_admin.py。

用法（凭据必须显式提供，代码中不内置固定管理员密码）：
    INIT_ADMIN_USERNAME=admin INIT_ADMIN_PASSWORD='Str0ng-Password!' python -m app.scripts.seed_admin

行为：
- 可重复执行：用户已存在时跳过创建，不覆盖密码
- 幂等：确保该用户拥有个人组织与 owner 成员行
- 若用户已存在且角色不是 admin，会打印提示但不会自动提权（避免误操作）
"""

from __future__ import annotations

import os
import sys

from sqlalchemy.orm import Session

from app.features.organizations.service import ensure_personal_organization
from app.models.identity import User
from app.shared.database import SessionLocal, engine
from app.shared.errors import bad_request
from app.shared.passwords import hash_password
from app.shared.roles import ROLE_PLATFORM_ADMIN


def require_credentials() -> tuple[str, str]:
    """从环境变量读取初始管理员凭据，并在格式不合规时终止流程。"""
    username = (os.getenv("INIT_ADMIN_USERNAME") or "").strip()
    password = os.getenv("INIT_ADMIN_PASSWORD") or ""
    if not username or not password:
        raise SystemExit(
            "缺少凭据：请设置 INIT_ADMIN_USERNAME 与 INIT_ADMIN_PASSWORD 环境变量后重试"
        )
    if len(username) < 3:
        raise bad_request("管理员用户名至少 3 个字符")
    if len(password) < 10:
        raise bad_request("初始管理员密码至少 10 位")
    return username, password


def seed(*, db: Session | None = None, username: str | None = None, password: str | None = None) -> tuple[User, bool]:
    """创建或确认管理员；返回 (user, created)。

    Args:
        db: 复用的会话；为 None 时自建会话并在函数结束时关闭。
        username: 管理员用户名；未提供时从环境变量读取校验。
        password: 明文密码；未提供时从环境变量读取校验。

    Returns:
        (user, created)：created 表示本次调用是否真的新建了账号。
    """
    if username is None or password is None:
        username, password = require_credentials()

    # own 标记「会话由本函数自己创建」，只有这种情况才需要在 finally 里关闭，
    # 否则调用方（如测试夹具）仍持有该会话的关闭权。
    own = db is None
    session: Session = db or SessionLocal()
    created = False
    try:
        existing = session.query(User).filter(User.username == username).first()
        if existing is not None:
            # 幂等分支：账号已存在时不覆盖历史密码，只补齐个人组织与 owner 成员行。
            if existing.role != ROLE_PLATFORM_ADMIN:
                print(f"[seed_admin] 用户 {username} 已存在但角色为 {existing.role}，未自动提权", file=sys.stderr)
            ensure_personal_organization(session, existing)
            session.commit()
            return existing, False

        user = User(
            username=username,
            hashed_password=hash_password(password),
            role=ROLE_PLATFORM_ADMIN,
            is_active=True,
            token_version=0,  # 新账号从 0 起算；改密/禁用/调角色时才递增
        )
        session.add(user)
        session.flush()
        ensure_personal_organization(session, user)
        session.commit()
        session.refresh(user)
        created = True
        return user, True
    finally:
        if own:
            session.close()


def main() -> None:
    """命令行入口：执行 seed() 并向 stderr/stdout 打印结果。"""
    try:
        user, created = seed()
    except Exception as exc:  # noqa: BLE001
        # 异常分支：把失败原因打到 stderr 并以非零码退出，便于 CI 判定失败。
        print(f"[seed_admin] 初始化失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    action = "已创建" if created else "已存在，跳过创建（密码保持不变）"
    print(f"[seed_admin] 管理员 {user.username} {action}，id={user.id}，role={user.role}")


if __name__ == "__main__":
    main()
