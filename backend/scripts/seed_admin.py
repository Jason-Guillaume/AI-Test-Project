"""首次初始化：创建数据库、执行迁移、写入初始数据。

用法（在 backend/ 目录下）：
    .venv/bin/python scripts/seed_admin.py          # 建库 + 迁移 + 种子数据
    .venv/bin/python scripts/seed_admin.py --drop   # 先删除数据库再重建（仅本地调试）

管理员凭据必须通过环境变量提供（INIT_ADMIN_USERNAME / INIT_ADMIN_PASSWORD），
脚本不在代码里内置任何默认账号或密码。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def split_database_url(url: str) -> tuple[str, str]:
    """把连接串拆成「可连接的管理员连接串」与目标库名。

    SQLAlchemy 连接串形如 ``postgresql+psycopg://user:pwd@host:port/db``，
    psycopg 不识别 ``+psycopg`` 方言标记，因此拆出主机与库名重新拼接，
    并去掉库名以使用管理员可访问的 ``postgres`` 维护库。
    """
    # 形如 postgresql+psycopg://user:pwd@host:port/dbname
    if "@" not in url:
        raise ValueError("DATABASE_URL 必须包含凭据部分")
    credentials, target = url.split("@", 1)
    scheme, _, auth_part = credentials.partition("://")
    scheme = scheme.split("+", 1)[0]
    # 去掉方言标记（如 +psycopg）：psycopg 驱动本身不识别这个后缀。
    # 主机与端口位于 @ 之后的 target 段，取第一个 "/" 之前的部分。
    host_part = target.split("/", 1)[0]
    database_name = target.rsplit("/", 1)[-1]
    # 管理员连接串指向 postgres 维护库，保留原始凭据与主机；
    # 因为 CREATE/DROP DATABASE 不能在待建的库上执行，必须先连维护库。
    return f"{scheme}://{auth_part}@{host_part}/postgres", database_name


def create_database(dsn_url: str, *, drop_first: bool = False) -> None:
    """幂等地创建目标数据库；drop_first 时先删除再重建。"""
    import psycopg

    admin_url, database_name = split_database_url(dsn_url)
    # autocommit=True：CREATE/DROP DATABASE 不能在事务里执行，必须自动提交。
    connection = psycopg.connect(admin_url, autocommit=True)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_database WHERE datname=%s", (database_name,))
            exists = cursor.fetchone() is not None
            if exists and drop_first:
                # 危险操作：drop_first 会不可恢复地删掉整个库，仅限本地调试使用。
                cursor.execute(f'DROP DATABASE "{database_name}"')
                exists = False
            if not exists:
                cursor.execute(f'CREATE DATABASE "{database_name}"')
                print(f"已创建数据库：{database_name}")
            else:
                print(f"数据库已存在：{database_name}")
    finally:
        connection.close()


def _alembic_config(dsn_url: str):
    """构造指向指定连接串的 Alembic 配置。"""
    from alembic.config import Config

    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", dsn_url)
    # script_location 指向 alembic 目录，确保在任意 cwd 下都能找到版本脚本。
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


def run_migrations(dsn_url: str) -> None:
    """执行 Alembic 迁移到最新版本。"""
    from alembic import command
    from alembic.script import ScriptDirectory

    os.environ["DATABASE_URL"] = dsn_url
    config = _alembic_config(dsn_url)
    # 幂等保护：无论 alembic_version 当前指向哪里，先盖回 base 再向上升级。
    # 这样重复执行本脚本不会报「版本已存在」，也不会把半迁移状态误判为已完成。
    command.stamp(config, "base")
    command.upgrade(config, "head")

    head = ScriptDirectory.from_config(config).get_current_head()
    print(f"迁移完成，当前版本：{head}")


def seed_builtin_environment(dsn_url: str) -> None:
    """写入内置环境行，保证环境选择器与执行链路有可用数据。"""
    # 必须在导入 app.shared.database 之前设置：engine 在首次导入时就按 DATABASE_URL 建好。
    os.environ["DATABASE_URL"] = dsn_url
    from app.features.environment_configuration.schemas import builtin_environments
    from app.models.configuration import Environment
    from app.shared.database import SessionLocal

    with SessionLocal() as session:
        # 幂等检查：已存在同名环境就跳过，重复执行脚本不会写入重复行。
        existing = {row[0] for row in session.query(Environment.name).all()}
        has_default = session.query(Environment).filter(
            Environment.is_default.is_(True)
        ).first() is not None
        added = 0
        for index, config in enumerate(builtin_environments()):
            name = config["name"]
            if name in existing:
                continue
            session.add(
                Environment(
                    name=name,
                    display_name=config.get("display_name") or name,
                    base_url=config.get("base_url") or "",
                    gateway_prefix=config.get("gateway_prefix") or "",
                    default_headers=dict(config.get("default_headers") or {}),
                    description=config.get("description"),
                    is_default=(index == 0 and not has_default),
                    is_active=True,
                )
            )
            # 只有库内还没有默认环境时，才把第一条内置环境设为兜底默认。
            added += 1
        session.commit()
        print(f"内置环境写入完成（新增 {added} 条）")


def seed_admin(dsn_url: str) -> str | None:
    """创建初始管理员与演示账号；已存在时跳过，不覆盖历史密码。"""
    # 同样要在导入 app.shared.database 之前设置 DATABASE_URL（见上方说明）。
    os.environ["DATABASE_URL"] = dsn_url
    from app.features.organizations.services.organization_service import ensure_personal_organization
    from app.models.identity import Organization, User
    from app.shared.database import SessionLocal
    from app.shared.passwords import hash_password

    username = (os.getenv("INIT_ADMIN_USERNAME") or "").strip()
    password = os.getenv("INIT_ADMIN_PASSWORD") or ""
    if not username or not password:
        print("未提供 INIT_ADMIN_USERNAME / INIT_ADMIN_PASSWORD，跳过管理员初始化")
        return None

    with SessionLocal() as session:
        # 幂等检查：已存在则直接返回，绝不覆盖用户后续改过的密码。
        if session.query(User).filter(User.username == username).first() is not None:
            print(f"管理员已存在，跳过：{username}")
            return username

        admin = User(username=username, hashed_password=hash_password(password), role="admin")
        session.add(admin)
        session.flush()
        ensure_personal_organization(session, admin)
        session.commit()
        session.refresh(admin)

        organization = (
            session.query(Organization)
            .filter(Organization.owner_id == admin.id)
            .order_by(Organization.id)
            .first()
        )
        print(f"管理员已创建：{username}（id={admin.id}，组织 id={organization.id if organization else '无'}）")
        return username


def main(argv: list[str]) -> int:
    """命令行入口：依次执行建库、迁移、写入种子数据，返回进程退出码。

    Args:
        argv: 命令行参数列表，不含程序名。

    Returns:
        0 表示成功；1 表示 DATABASE_URL 缺失等前置条件不满足。
    """
    parser = argparse.ArgumentParser(description="初始化数据库与种子数据")
    parser.add_argument("--database-url", help="覆盖 DATABASE_URL")
    parser.add_argument("--skip-admin", action="store_true", help="只建库与迁移")
    parser.add_argument("--drop", action="store_true", help="先删除目标数据库（仅本地调试）")
    args = parser.parse_args(argv)

    # 命令行 --database-url 必须先于任何 app 导入生效：app.shared.database 在首次
    # 导入时用 settings.DATABASE_URL 建好 engine，之后再改 os.environ 也不影响它。
    # 否则会出现「迁移打到 A 库、种子数据写进 .env 里的 B 库」这种静默错库。
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url

    from app.shared.config import settings

    dsn_url = args.database_url or settings.DATABASE_URL
    if not dsn_url:
        print("DATABASE_URL 未配置，请通过环境变量或 .env 提供")
        return 1

    # 执行顺序不能变：先建库、再迁移、最后写种子数据；
    # 前三步全部针对同一个 dsn_url，避免步骤之间打到不同的库。
    create_database(dsn_url, drop_first=args.drop)
    run_migrations(dsn_url)
    if not args.skip_admin:
        seed_builtin_environment(dsn_url)
        seed_admin(dsn_url)
    print("初始化完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
