"""数据库连接层。

- engine：连接 PostgreSQL（同步访问，沿用旧项目 SQLAlchemy 同步 Session）
- SessionLocal：每次请求创建会话
- get_db：FastAPI 依赖注入，请求结束自动关闭连接
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.shared.config import settings

# 连接池参数：非 PostgreSQL 数据源（例如测试用的 SQLite）只保留 pool_pre_ping，
# 其余 pool_* 参数仅在真实 PostgreSQL 下开启。
engine_kwargs: dict[str, object] = {"pool_pre_ping": True}
if settings.DATABASE_URL and settings.DATABASE_URL.startswith(("postgresql", "postgres")):
    engine_kwargs.update(
        {
            "pool_size": max(1, settings.DB_POOL_SIZE),
            "max_overflow": max(0, settings.DB_MAX_OVERFLOW),
            "pool_timeout": max(1, settings.DB_POOL_TIMEOUT_SECONDS),
            "pool_recycle": max(60, settings.DB_POOL_RECYCLE_SECONDS),
        }
    )

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)  # type: ignore[arg-type]

# expire_on_commit=False：commit 之后对象属性不失效，便于事务提交后直接回读对象字段。
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。

    各 models 模块的表定义都继承自它；Alembic 的 metadata 也指向同一份，
    保证变更脚本与实际模型始终一致。
    """


def get_db() -> Iterator[Session]:
    """依赖注入：yield 会话，请求结束后 close，防止连接泄漏。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
