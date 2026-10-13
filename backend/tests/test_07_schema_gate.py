"""验收项 10：应用启动不自动改表结构。

- AUTO_CREATE_SCHEMA=false（默认）时启动应用不会创建任何表
- AUTO_CREATE_SCHEMA=true（本地首次调试开关）时才 create_all
- 正式表结构只能通过 Alembic 迁移生成

探测在独立子进程里进行：Settings 在导入时即读取环境变量，必须用干净的进程
隔离开关，而不是在同一解释器里改 os.environ。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

from tests.conftest import ADMIN_DSN, BACKEND_DIR, EXPECTED_TABLES, psycopg

# 两个独立的探测库名：分别验证「默认不建表」与「开关打开才建表」，互不干扰。
GATE_DB = "testplatform_gate"
CREATE_DB = "testplatform_gate_create"
TEST_DSN = os.environ["DATABASE_URL"]
TEST_DATABASE_NAME = os.environ.get("TEST_DATABASE_NAME", "testplatform_test")

# 子进程里跑的探测脚本：启动应用、请求健康检查，再反射表结构。
# 必须走独立进程，因为 Settings 在导入时即固化环境变量，同一解释器内改
# os.environ 无法重置开关；返回值只通过 stdout 最后一行的 JSON 传回来。
PROBE = """
import json
import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.main import app
from app.shared.config import settings

with TestClient(app) as client:
    health = client.get("/healthz")
    meta = client.get("/api/v1/meta")
    assert health.status_code == 200, health.text
    assert meta.status_code == 200, meta.text

    engine = create_engine(os.environ["DATABASE_URL"])

tables = sorted(t for t in inspect(engine).get_table_names() if t != "alembic_version")
print(json.dumps({"tables": tables, "flag": settings.AUTO_CREATE_SCHEMA}))
"""


def _prepare(name: str) -> None:
    """把目标库重置成空库：先断开残留连接，再 DROP / CREATE。

    必须用 ADMIN_DSN（连 postgres 维护库）才能执行 DROP / CREATE DATABASE。

    Args:
        name: 要重建的库名。
    """
    with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
        with connection.cursor() as cursor:
            _terminate(cursor, name)
            cursor.execute(f'DROP DATABASE IF EXISTS "{name}"')
            cursor.execute(f'CREATE DATABASE "{name}"')


def _terminate(cursor, name: str) -> None:
    """断开指向目标库的连接，便于删除与重建。"""
    cursor.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname=%s AND pid <> pg_backend_pid()",
        (name,),
    )


def _dsn(name: str) -> str:
    """复用测试库的连接参数，只替换库名，保证指向同一台隔离 PostgreSQL。"""
    return TEST_DSN.replace(f"/{TEST_DATABASE_NAME}", f"/{name}")


def _run_probe(database: str, auto_create: str) -> dict:
    """在独立子进程里跑 PROBE 探测，返回 {tables, flag} 字典。

    Args:
        database: 探测库名，DSN 复用测试库参数只换库名。
        auto_create: AUTO_CREATE_SCHEMA 开关取值（"true" / "false"）。
    Returns:
        dict: tables 为已排序的表名列表（剔除 alembic_version），flag 为进程内生效的开关。
    """
    # INIT_ADMIN_* 置空而不是删键：dotenv 会跳过已有键，避免 .env 的开发凭据被灌回。
    env = {
        key: ("" if key in {"INIT_ADMIN_USERNAME", "INIT_ADMIN_PASSWORD"} else value)
        for key, value in os.environ.items()
    }
    env["DATABASE_URL"] = _dsn(database)
    env["AUTO_CREATE_SCHEMA"] = auto_create
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_startup_does_not_create_schema_by_default():
    """不变量：默认配置下应用启动不建任何表，正式表结构只能由 Alembic 迁移产生。

    验收点：开关生效值为 False，且库里除 alembic_version 外没有任何表——
    这说明启动期不会 create_all，也不会建 alembic_version 之外的表。
    """
    _prepare(GATE_DB)
    try:
        payload = _run_probe(GATE_DB, "false")
    finally:
        # 无论断言成败都要清掉探测库，否则下次重建会被残留连接挡住。
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            with connection.cursor() as cursor:
                _terminate(cursor, GATE_DB)
                cursor.execute(f'DROP DATABASE IF EXISTS "{GATE_DB}"')

    assert payload["flag"] is False
    assert payload["tables"] == []


def test_create_all_only_when_flag_is_enabled():
    """不变量：只有 AUTO_CREATE_SCHEMA=true 时才 create_all，这是本地首次调试的开关。

    验收点：开关生效值为 True，且 EXPECTED_TABLES 里 9 张业务表全部就位。
    """
    _prepare(CREATE_DB)
    try:
        payload = _run_probe(CREATE_DB, "true")
    finally:
        # 同样兜底清理探测库，避免残留连接影响下次会话。
        with psycopg.connect(ADMIN_DSN, autocommit=True) as connection:
            with connection.cursor() as cursor:
                _terminate(cursor, CREATE_DB)
                cursor.execute(f'DROP DATABASE IF EXISTS "{CREATE_DB}"')

    assert payload["flag"] is True
    assert EXPECTED_TABLES.issubset(set(payload["tables"]))
