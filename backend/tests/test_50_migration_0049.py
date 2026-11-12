"""0048 → 0049 迁移兼容验收。

不用清库方式绕过：先在 0048 建真实批次与草稿数据，再升级 0049，
验证旧数据保留、original_payload 回填、部分唯一索引与审计表生效。
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.conftest import TEST_DB_HOST, TEST_DB_PASSWORD, TEST_DB_PORT, TEST_DB_USER

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _url(database: str) -> str:
    """组装指向指定库的连接串（不带 search_path，默认 public）。"""
    return f"postgresql+psycopg://{TEST_DB_USER}:{TEST_DB_PASSWORD}@{TEST_DB_HOST}:{TEST_DB_PORT}/{database}"


def _admin_conn() -> psycopg.Connection:
    """连到 postgres 管理库，用于建删 scratch 库。"""
    return psycopg.connect(
        f"postgresql://{TEST_DB_USER}:{TEST_DB_PASSWORD}@{TEST_DB_HOST}:{TEST_DB_PORT}/postgres",
        autocommit=True,
    )


def _recreate(name: str) -> None:
    """重建 scratch 库（仅本测试独占的新库，不触碰共享库）。"""
    with _admin_conn() as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        conn.execute(f'CREATE DATABASE "{name}"')


def _drop(name: str) -> None:
    """删除 scratch 库。"""
    with _admin_conn() as conn:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
            (name,),
        )
        conn.execute(f'DROP DATABASE IF EXISTS "{name}"')


def _upgrade(database: str, target: str) -> None:
    """对指定库执行 alembic upgrade；env.py 只认 DATABASE_URL 环境变量。"""
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = _url(database)
    try:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        command.upgrade(config, target)
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest.fixture()
def scratch():
    """每个用例一个独占 scratch 库，结束即删。"""
    name = f"testplatform_mig_{uuid.uuid4().hex[:8]}"
    _recreate(name)
    try:
        yield name
    finally:
        _drop(name)


def test_fresh_database_upgrades_to_head_with_0049_objects(scratch, test_database_head):
    """空库升级到 head：0049 的表、列与部分唯一索引全部就位。"""
    _upgrade(scratch, "base")
    _upgrade(scratch, test_database_head)
    with psycopg.connect(_url(scratch).replace("+psycopg", "")) as conn:
        tables = {row[0] for row in conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
        )}
        assert "case_generation_audit" in tables
        columns = {row[0] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'case_draft'",
        )}
        assert {"original_payload_json", "quality_json", "review_comment", "reviewed_by", "reviewed_at", "import_error"} <= columns
        indexes = {row[0] for row in conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'case_draft'",
        )}
        assert "uq_case_draft_test_case" in indexes


def test_0048_data_survives_upgrade_to_0049(scratch, test_database_head):
    """0048 的旧批次与草稿升级后保留，原文回填，约束与审计表生效。"""
    _upgrade(scratch, "base")
    _upgrade(scratch, "0048")
    plain = _url(scratch).replace("+psycopg", "")
    with psycopg.connect(plain, autocommit=True) as conn:
        # 0048 视角的最小外键链：用户 → 组织 → 项目 → 用例 → 批次 → 草稿。
        conn.execute('INSERT INTO "user" (username, hashed_password) VALUES (\'迁移用户\', \'x\')')
        conn.execute("INSERT INTO organization (name, owner_id) VALUES ('迁移组织', 1)")
        conn.execute("INSERT INTO project (name, organization_id, owner_id) VALUES ('迁移项目', 1, 1)")
        conn.execute("INSERT INTO test_case (project_id, name) VALUES (1, '迁移前用例')")
        conn.execute(
            """
            INSERT INTO case_generation_batch
                (project_id, direction, supervisor_version, supervisor_name, requirements,
                 modules_json, status, review_gaps_json, module_errors_json)
            VALUES (1, 'API', 3, '旧主 Agent', '旧需求', '["api"]', 'PARTIAL_FAILED', '[]', '[]')
            """,
        )
        conn.execute(
            """
            INSERT INTO case_draft (batch_id, module, title, priority, payload_json, skill_versions_json, status, test_case_id)
            VALUES (1, 'api', '旧草稿', 'P1', '{"title": "旧草稿"}', '[]', 'ACCEPTED', 1)
            """,
        )
    _upgrade(scratch, test_database_head)
    with psycopg.connect(plain, autocommit=True) as conn:
        row = conn.execute(
            "SELECT payload_json, original_payload_json, quality_json, status FROM case_draft WHERE id = 1",
        ).fetchone()
        assert row is not None, "0048 的草稿在升级后丢失"
        assert row[0] == {"title": "旧草稿"}
        assert row[1] == {"title": "旧草稿"}, "original_payload_json 应由 payload_json 回填"
        assert row[2] == []
        assert row[3] == "ACCEPTED"
        batch = conn.execute("SELECT supervisor_name, module_metrics_json FROM case_generation_batch WHERE id = 1").fetchone()
        assert batch[0] == "旧主 Agent"
        assert batch[1] == []
        # 部分唯一索引：第二条草稿引用同一 test_case_id 必须失败。
        conn.execute(
            """
            INSERT INTO case_draft (batch_id, module, title, priority, payload_json, skill_versions_json, original_payload_json, status)
            VALUES (1, 'api', '新草稿', 'P1', '{}', '[]', '{}', 'PENDING')
            """,
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                """
                INSERT INTO case_draft (batch_id, module, title, priority, payload_json, skill_versions_json, original_payload_json, status, test_case_id)
                VALUES (1, 'api', '冲突草稿', 'P1', '{}', '[]', '{}', 'PENDING', 1)
                """,
            )
        # 审计表可写。
        conn.execute(
            """
            INSERT INTO case_generation_audit (project_id, batch_id, draft_id, action, detail_json)
            VALUES (1, 1, 1, 'APPROVE', '{"test_case_id": 1}')
            """,
        )
        count = conn.execute("SELECT count(*) FROM case_generation_audit").fetchone()[0]
        assert count == 1
