"""Alembic 运行环境。

连接串只从环境变量 DATABASE_URL 读取（与运行期使用同一份配置），
并把 core 基线模型与各能力包模型注册进 metadata，便于 autogenerate。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.database.base import Base

# 确保所有 ORM 模型被导入并注册进 Base.metadata。
import app.core.models  # noqa: F401
# 领域 ORM 模型由 Alembic 明确发现，不反向扩展 app.core.models/__init__.py。
from app.agents import models as agent_models  # noqa: F401
from app.mcp import models as mcp_models  # noqa: F401
from app.skills import models as skill_models  # noqa: F401
from app.tools import models as tool_models  # noqa: F401
from app.platform.environment_configuration import models as environment_models  # noqa: F401
from app.platform.notifications import models as notification_models  # noqa: F401
from app.features.api_catalog import models as api_catalog_models  # noqa: F401
from app.features.business import models as business_models  # noqa: F401
from app.features.business.models.execution import ActionExecution, FlowExecution  # noqa: F401
from app.features.defects import models as defect_models  # noqa: F401
from app.features.mocking import models as mock_models  # noqa: F401
from app.features.reports import models as report_models  # noqa: F401
from app.features.security_testing import models as security_models  # noqa: F401
from app.features.security_testing.zap import models as zap_models  # noqa: F401
from app.orchestration.tasks import models as task_models  # noqa: F401
from app.features.test_data import models as test_data_models  # noqa: F401
from app.features.test_management import models as test_management_models  # noqa: F401
from app.features.web_testing import models as web_ui_models  # noqa: F401

# Alembic 传入的运行时配置对象，后面会覆盖其中的数据库 URL。
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata 是 autogenerate 的比较基准：ORM 模型即「真源」，
# 迁移内容应始终由模型推导，而不是手写 SQL。
target_metadata = Base.metadata

# 环境变量优先于 alembic.ini 中的占位符。
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    """离线模式：只生成 SQL，不连接数据库。"""
    url = config.get_main_option("sqlalchemy.url")
    # 离线模式渲染成可直接审阅的 SQL 文件，因此参数要写死成字面量。
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,  # 参数渲染为字面量，而不是绑定占位符
        dialect_opts={"paramstyle": "named"},  # 与 literal_binds 配套的命名参数风格
        compare_type=True,  # 让 autogenerate 也能发现列类型变更（默认只比有无变更）
        render_as_batch=False,  # PostgreSQL 原生支持 ALTER，无需 SQLite 式批量重建表
    )
    # 整个迁移版本包在一个事务里：任一步失败即全部回滚，不会留下半迁移状态。
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线模式：连接数据库执行迁移。"""
    # 迁移是一次性任务，不需要连接池；NullPool 可避免连接被复用带来的状态残留。
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # 在线模式复用同一条连接跑完所有版本，autogenerate 配置与离线模式保持一致。
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_as_batch=False,
        )
        # 提交点：一个事务覆盖整批版本，任一步失败即整体回滚。
        with context.begin_transaction():
            context.run_migrations()


# 按运行方式二选一：--sql / offline 走离线渲染，其余情况连接数据库实际执行。
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
