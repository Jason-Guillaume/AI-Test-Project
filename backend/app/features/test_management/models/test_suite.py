"""测试套件（Test Suite）ORM 模型。

测试套件是测试用例的集合容器，归属于项目。TestSuiteCase 为套件-用例关联表
（CASCADE 删除：套件删则关联删，但用例保留）。

suite_type ∈ {SMOKE, REGRESSION, BUSINESS, CUSTOM}。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class TestSuite(Base):
    """测试套件：测试用例的集合容器。"""

    __tablename__ = "test_suite"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_test_suite_project_name"),
        Index("ix_test_suite_project_enabled", "project_id", "enabled"),
        {"comment": "测试套件：测试用例的集合容器"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属项目ID",
    )
    name = Column(String(200), nullable=False, comment="套件名")
    description = Column(String(1000), nullable=True, comment="套件描述")
    suite_type = Column(
        String(20), nullable=False, default="REGRESSION", server_default=text("'REGRESSION'"),
        comment="套件类型：SMOKE/REGRESSION/BUSINESS/CUSTOM",
    )
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True, comment="创建人")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )


class TestSuiteCase(Base):
    """套件-用例关联。"""

    __tablename__ = "test_suite_case"
    __table_args__ = (
        UniqueConstraint("suite_id", "test_case_id", name="uq_test_suite_case_suite_case"),
        Index("ix_test_suite_case_suite_sort", "suite_id", "sort"),
        {"comment": "套件-用例关联"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    suite_id = Column(
        Integer,
        ForeignKey("test_suite.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属套件ID",
    )
    test_case_id = Column(
        Integer,
        ForeignKey("test_case.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用例ID",
    )
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否启用")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
