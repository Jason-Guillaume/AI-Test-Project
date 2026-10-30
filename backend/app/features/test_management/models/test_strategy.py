"""测试策略（Test Strategy）ORM 模型。

测试策略是测试资产的最高层级：从业务视角描述「测什么维度」
（功能 / 参数 / 边界 / 权限 / 安全 / 业务 / 异常 / 幂等 / 数据一致性）。
归属于项目；其下挂载若干测试点（TestPoint）。

category ∈ {FUNCTIONAL, PARAMETER, BOUNDARY, AUTH, PERMISSION, BUSINESS,
EXCEPTION, IDEMPOTENCY, SECURITY, DATA_CONSISTENCY}，由服务层校验。
source_type ∈ {MANUAL, AI}，本阶段仅 MANUAL，预留 AI。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class TestStrategy(Base):
    """测试策略：项目下某一测试维度的策略定义。"""

    __tablename__ = "test_strategy"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_strategy_project_name"),
        Index("ix_test_strategy_project_category", "project_id", "category"),
        {"comment": "测试策略：项目下某一测试维度的策略定义"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    name = Column(String(200), nullable=False, comment="策略名称")
    description = Column(String(1000), nullable=True, comment="策略描述")
    category = Column(
        String(50), nullable=False, default="FUNCTIONAL", server_default=text("'FUNCTIONAL'"),
        index=True, comment="策略类别：FUNCTIONAL/PARAMETER/BOUNDARY/AUTH/PERMISSION/BUSINESS/EXCEPTION/IDEMPOTENCY/SECURITY/DATA_CONSISTENCY",
    )
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用")
    source_type = Column(
        String(20), nullable=False, default="MANUAL", server_default=text("'MANUAL'"),
        comment="来源：MANUAL/AI（预留）",
    )
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
