"""验收项 1、2：

1. Alembic 可在隔离 PostgreSQL 上从空库升级到 head，并生成约定的 9 张表
2. 管理员初始化命令可重复执行（幂等），且不内置固定管理员密码
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

from tests.conftest import (
    ADMIN_DSN,
    BACKEND_DIR,
    EXPECTED_TABLES,
    TEST_DATABASE_NAME,
    TEST_DSN,
    psycopg,
)

# 种子脚本与被验证的凭据：密码故意用测试专用值，不能出现在脚本输出里。
SEED_SCRIPT = BACKEND_DIR / "scripts" / "seed_admin.py"
SEED_USER = "seed-admin-001"
SEED_PASSWORD = "Seed-Password-789"


def test_alembic_upgrades_empty_database_to_head(db):
    """不变量：表结构唯一来源是 Alembic 迁移，而不是应用启动期 create_all。

    验收点：
    - alembic_version 表里记录的是 head 版本，说明「迁移真的跑过了」；
    - information_schema 中能看到 EXPECTED_TABLES 全部业务表；
    - 连接对象是全新 Session（db fixture），说明写进的是数据库而不是内存。
    """
    head = db.execute(text("select version_num from alembic_version")).scalar()
    # head 随版本链演进；当前 head 为 0017
    #（0005 业务执行引擎 + 0006 测试管理 + 0007 Agent + 0008 报告/通知
    #  + 0009 测试数据中心 + Data Factory + 0010 Mock Management
    #  + 0011 Security Testing + 0012 Web UI 自动化一期 + 0013 ZAP 安全扫描
    #  + 0014 Web UI 智能体二期 + 0015 统一任务调度）。
    assert head == "0017"

    tables = {
        row[0]
        for row in db.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public' and table_type = 'BASE TABLE'"
            )
        )
    }
    # 业务表集合必须是期望集合的子集校验（允许未来新增表，不允许缺表）。
    assert EXPECTED_TABLES.issubset(tables), tables
    assert "alembic_version" in tables


ADMIN_CRED_ENV_KEYS = ("INIT_ADMIN_USERNAME", "INIT_ADMIN_PASSWORD")


def _run_seed(extra_env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """在独立进程中执行初始化脚本；凭据环境变量一律置空以验证「必须显式提供」。

    注意不能直接删掉这两个键：app.shared.config 在导入时会 load_dotenv()，
    工作目录下 backend/.env 里的开发凭据会被重新灌进环境变量，导致「未提供
    凭据」分支测不到。置为空串后 dotenv 不会覆盖已有值，脚本读到空值即跳过。

    Args:
        extra_env: 需要额外注入的环境变量（例如 INIT_ADMIN_USERNAME）。
    Returns:
        CompletedProcess: 子进程结果，调用方按 stdout 文案断言分支走向。
    """
    env = {
        key: ("" if key in ADMIN_CRED_ENV_KEYS else value)
        for key, value in os.environ.items()
    }
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(SEED_SCRIPT), "--database-url", TEST_DSN],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_seed_admin_requires_env_and_is_idempotent(db):
    """不变量：管理员只能由显式凭据创建，且重复初始化不产生重复行。

    三段式验收：
    1. 无凭据 -> 脚本成功但走「跳过」分支（不会凭空造出管理员）；
    2. 有凭据 -> 首次创建管理员与内置环境；
    3. 同样凭据再跑一次 -> 只跳过，用户数仍为 1、角色仍为 admin。
    """
    without_creds = _run_seed({})
    assert without_creds.returncode == 0, without_creds.stdout + without_creds.stderr
    assert "跳过管理员初始化" in without_creds.stdout

    first = _run_seed(
        {"INIT_ADMIN_USERNAME": SEED_USER, "INIT_ADMIN_PASSWORD": SEED_PASSWORD}
    )
    assert first.returncode == 0, first.stdout + first.stderr
    assert f"管理员已创建：{SEED_USER}" in first.stdout
    assert "内置环境写入完成" in first.stdout

    second = _run_seed(
        {"INIT_ADMIN_USERNAME": SEED_USER, "INIT_ADMIN_PASSWORD": SEED_PASSWORD}
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert f"管理员已存在，跳过：{SEED_USER}" in second.stdout

    # 用原生 SQL 直接数行数：重复执行绝不能变成 2 行。
    count = db.execute(
        text('select count(*) from "user" where username = :u'), {"u": SEED_USER}
    ).scalar()
    assert count == 1
    role = db.execute(
        text('select role from "user" where username = :u'), {"u": SEED_USER}
    ).scalar()
    assert role == "admin"

    # 内置环境同样幂等：重复初始化不会插入重复行。
    names = [row[0] for row in db.execute(text("select name from environment"))]
    assert {"dev", "test", "staging", "prod"}.issubset(set(names))
    assert len(names) == len(set(names))


def test_seed_admin_does_not_print_credentials(db):
    """不变量：初始化输出不得回显数据库密码或管理员密码（密钥掩码约定）。

    顺带覆盖两类敏感串：开发库口令（backend/.env 里的那个）与历史遗留的
    占位默认管理员密码，它们都不该出现在 stdout/stderr 中。
    """
    result = _run_seed(
        {"INIT_ADMIN_USERNAME": SEED_USER, "INIT_ADMIN_PASSWORD": SEED_PASSWORD}
    )
    combined = result.stdout + result.stderr
    assert SEED_PASSWORD not in combined
    for sensitive in ("fangzhou123", "Admin-Change-Me-123"):
        assert sensitive not in combined


TARGET_ADMIN = "seed-target-admin"
TARGET_DATABASE = "testplatform_seedtarget"


def _seed_into_target_database() -> str:
    """把 --database-url 指向一个独立库，验证种子数据确实写进它。

    先 DROP 再 CREATE，保证目标库是空库——否则残留行会让「写到了哪个库」
    的判断失效。

    Returns:
        str: 指向目标库的 DSN（复用测试库的连接参数，仅换库名）。
    """
    target_dsn = TEST_DSN.replace(f"/{TEST_DATABASE_NAME}", f"/{TARGET_DATABASE}")
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        connection.execute(f'DROP DATABASE IF EXISTS "{TARGET_DATABASE}"')
        connection.execute(f'CREATE DATABASE "{TARGET_DATABASE}"')
    return target_dsn


def _run_seed_into(target_dsn: str) -> subprocess.CompletedProcess[str]:
    """命令行库（target_dsn）与进程内生效的库（TEST_DSN）不同的现场。

    DATABASE_URL 固定指向隔离测试库而不是删掉它：删掉会让 seed 回落到
    backend/.env 里的开发库，失败用例就会把真实开发库污染掉。
    """
    env = dict(os.environ)
    env["DATABASE_URL"] = TEST_DSN
    env["INIT_ADMIN_USERNAME"] = TARGET_ADMIN
    env["INIT_ADMIN_PASSWORD"] = SEED_PASSWORD
    return subprocess.run(
        [sys.executable, str(SEED_SCRIPT), "--database-url", target_dsn],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_seed_admin_targets_the_database_named_on_the_command_line(db):
    """--database-url 与 .env 里的库不同时，种子数据必须写进命令行指定的那个库。

    回归用例：app.shared.database 在首次导入时用 settings.DATABASE_URL 建好 engine，
    若 --database-url 的覆盖发生在导入之后，就会出现「迁移打到目标库、种子数据
    却写进 .env 库」的静默错库。

    验收点：目标库里管理员计数为 1、内置环境为 4；隔离测试库里同名的行数为 0。
    """
    target_dsn = _seed_into_target_database()
    try:
        result = _run_seed_into(target_dsn)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"管理员已创建：{TARGET_ADMIN}" in result.stdout

        # 用独立连接直连目标库核对（转成 libpq 形式的 DSN）。
        with psycopg.connect(
            target_dsn.replace("postgresql+psycopg", "postgresql"), autocommit=True
        ) as target:
            target_count = target.execute(
                'select count(*) from "user" where username = %s', (TARGET_ADMIN,)
            ).fetchone()[0]
            target_envs = target.execute("select count(*) from environment").fetchone()[0]
        assert target_count == 1, "管理员没有写进 --database-url 指定的库"
        assert target_envs == 4, "内置环境没有写进 --database-url 指定的库"

        # 测试库不能被污染：同样的用户名与内置环境数不应在这里出现。
        leak = db.execute(
            text('select count(*) from "user" where username = :u'),
            {"u": TARGET_ADMIN},
        ).scalar()
        assert leak == 0, "种子数据写进了 .env / 环境变量里的库（错库）"
    finally:
        # 无论断言成败都要回收临时库，避免下次会话重建时连接被占用。
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{TARGET_DATABASE}"')
