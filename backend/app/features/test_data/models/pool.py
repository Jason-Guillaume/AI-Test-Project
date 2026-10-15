"""数据池 ORM 模型：池、条目、租约。

占用算法：`SELECT ... WHERE pool_id=? AND status='AVAILABLE' AND occupied_count < max
FOR UPDATE SKIP LOCKED`。租约到期由领取时懒更新为 EXPIRED，第一阶段不加定时任务；
释放在 Cleanup 里做，且 cleanup_policy=NEVER 也必须释放租约，否则并发槽泄漏。

模型 feature-local，不进 app/models/__init__.py；由 alembic 0009 显式建表。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class DataPool(Base):
    """数据池：可并发占用的共享测试数据集合。"""

    __tablename__ = "data_pool"
    __table_args__ = (
        UniqueConstraint("project_id", "pool_key", name="uq_data_pool_project_key"),
        {"comment": "数据池：可并发占用的共享测试数据集合"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    asset_id = Column(
        Integer, ForeignKey("test_data_asset.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联的测试数据资产（可空）",
    )
    pool_key = Column(String(100), nullable=False, comment="池键：^[A-Z][A-Z0-9_]{0,99}$")
    name = Column(String(200), nullable=False, comment="池名称")
    scope = Column(
        String(20), nullable=False, default="PROJECT", server_default=text("'PROJECT'"),
        comment="作用域：CASE/RUN/PROJECT/GLOBAL，默认 PROJECT",
    )
    max_concurrency = Column(
        Integer, nullable=False, default=1, server_default=text("1"),
        comment="最大并发占用数（共享只读数据可大于 1）",
    )
    lease_ttl_seconds = Column(
        Integer, nullable=False, default=1800, server_default=text("1800"),
        comment="租约有效期（秒）",
    )
    status = Column(
        String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"),
        comment="状态：ACTIVE/DISABLED",
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )


class DataPoolItem(Base):
    """池条目。payload 脱敏后落库，占用计数由执行引擎维护。"""

    __tablename__ = "data_pool_item"
    __table_args__ = (
        Index("ix_data_pool_item_available", "pool_id", "status"),
        {"comment": "池条目：payload 脱敏后落库，占用计数由执行引擎维护"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    pool_id = Column(
        Integer, ForeignKey("data_pool.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属池ID",
    )
    status = Column(
        String(20), nullable=False, default="AVAILABLE", server_default=text("'AVAILABLE'"),
        comment="状态：AVAILABLE/OCCUPIED/EXPIRED/DISABLED",
    )
    payload_json = Column(
        JSON, nullable=False, default=dict, server_default=text("'{}'"),
        comment="条目数据（脱敏后）",
    )
    occupied_count = Column(
        Integer, nullable=False, default=0, server_default=text("0"), comment="当前占用数",
    )
    expires_at = Column(DateTime, nullable=True, comment="条目自身过期时间")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )


class DataPoolLease(Base):
    """池租约：绑定 TestRun / CaseExecution，Run 结束必须释放。"""

    __tablename__ = "data_pool_lease"
    __table_args__ = ({"comment": "池租约：绑定 TestRun / CaseExecution，Run 结束必须释放"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    item_id = Column(
        Integer, ForeignKey("data_pool_item.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="被占用的条目ID",
    )
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="占用方项目ID",
    )
    test_run_id = Column(
        Integer, ForeignKey("test_run.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="占用方 TestRun ID",
    )
    case_execution_id = Column(
        Integer, ForeignKey("case_execution.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="占用方 CaseExecution ID",
    )
    status = Column(
        String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"),
        comment="状态：ACTIVE/RELEASED/EXPIRED",
    )
    leased_at = Column(DateTime, nullable=True, comment="占用时间")
    released_at = Column(DateTime, nullable=True, comment="释放时间")
    expires_at = Column(DateTime, nullable=True, comment="租约到期时间")
