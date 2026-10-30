"""core 归并回归测试。

验证规范 core 导入保持轻量、核心模型仍只注册九张基线表、数据库会话 flag 不变；
这些用例不创建或连接数据库，隔离库行为仍由现有迁移与业务测试覆盖。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run_python(script: str) -> subprocess.CompletedProcess[str]:
    """在隔离解释器中检查 core 导入行为，避免当前测试进程的模块缓存干扰。"""
    env = os.environ.copy()
    env["DATABASE_URL"] = "sqlite:///:memory:"
    env["AUTO_CREATE_SCHEMA"] = "false"
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_importing_core_does_not_load_runtime_or_business_packages() -> None:
    """验证导入 app.core 不初始化数据库会话或加载上层业务包。"""
    result = _run_python(
        "import sys; import app.core; "
        "assert 'app.core.database.session' not in sys.modules; "
        "assert 'app.core.models' not in sys.modules; "
        "assert not any(name == 'app.agents' or name.startswith('app.agents.') "
        "for name in sys.modules); "
        "assert not any(name.startswith('app.features.') for name in sys.modules)"
    )
    assert result.returncode == 0, result.stderr


def test_core_models_register_only_the_nine_baseline_tables() -> None:
    """验证规范模型入口只注册九张基线表，且不会创建数据库 session。"""
    script = """
import sys
import app.core.models
from app.core.database.base import Base

expected_tables = {
    "user",
    "organization",
    "organization_member",
    "project",
    "project_member",
    "project_outbound_target",
    "model_configuration",
    "environment",
    "notification",
}
assert set(Base.metadata.tables) == expected_tables
assert "app.core.database.session" not in sys.modules
assert not any(name == "app.agents" or name.startswith("app.agents.") for name in sys.modules)
assert not any(name.startswith("app.features.") for name in sys.modules)
"""
    result = _run_python(script)
    assert result.returncode == 0, result.stderr


def test_session_factory_keeps_explicit_transaction_flags() -> None:
    """验证唯一规范 SessionLocal 保留显式事务和提交后读配置。"""
    result = _run_python(
        "from app.core.database.session import SessionLocal; "
        "assert SessionLocal.kw['autocommit'] is False; "
        "assert SessionLocal.kw['autoflush'] is False; "
        "assert SessionLocal.kw['expire_on_commit'] is False"
    )
    assert result.returncode == 0, result.stderr
