"""测试数据目录项 ORM 模型。

「测试数据」页的目录项：静态样本、池的逻辑分组、或由 Fixture 登记的可检索数据。
它不是 Fixture 配方——Fixture 描述「怎么造」，资产描述「这份数据是什么」。

value_json 入库前可以是明文（项目内配置），读 API 必须脱敏。
模型 feature-local，不进 app/models/__init__.py；由 alembic 0009 显式建表。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.shared.database import Base


class TestDataAsset(Base):
    """测试数据目录项。"""

    __tablename__ = "test_data_asset"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_data_asset_project_name"),
        Index("ix_test_data_asset_project_entity", "project_id", "entity_type", "status"),
        {"comment": "测试数据目录项：静态样本 / 池分组 / Fixture 登记的可检索数据"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer, ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属项目ID",
    )
    name = Column(String(200), nullable=False, comment="资产名称")
    entity_type = Column(String(50), nullable=False, comment="实体类型：USER/PROJECT/TASK 等")
    source = Column(
        String(30), nullable=False, default="STATIC", server_default=text("'STATIC'"),
        comment="来源：STATIC/POOL/FIXTURE",
    )
    scope = Column(
        String(20), nullable=False, default="PROJECT", server_default=text("'PROJECT'"),
        comment="作用域：CASE/RUN/PROJECT/GLOBAL（同 Fixture scope 语义）",
    )
    status = Column(
        String(20), nullable=False, default="ACTIVE", server_default=text("'ACTIVE'"),
        comment="状态：ACTIVE/DISABLED/EXPIRED",
    )
    fixture_id = Column(
        Integer, ForeignKey("fixture.id", ondelete="SET NULL"),
        nullable=True, index=True,
        comment="由哪个 Fixture 登记（可空）",
    )
    value_json = Column(JSON, nullable=True, comment="静态值（读 API 必须脱敏）")
    description = Column(String(500), nullable=True, comment="说明")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
