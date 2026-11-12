"""用例 ↔ Fixture 关联 ORM 模型。

用例声明需要的 Fixture，不存运行时 ID。用例上出现的只有 fixture_key 与输出名，
真实 task_id 等运行时值由 Data Factory 在 Run 时注入 ExecutionContext。

fixture_id 是 RESTRICT：被引用的 Fixture 不允许直接删除（服务层先返回 409，
说明该 Fixture 仍被哪些用例引用）。

模型 feature-local，不进 app/models/__init__.py；由 alembic 0009 显式建表。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class TestCaseFixture(Base):
    """用例声明所需 Fixture。"""

    __tablename__ = "test_case_fixture"
    __table_args__ = (
        UniqueConstraint("test_case_id", "fixture_id", name="uq_test_case_fixture"),
        {"comment": "用例声明所需 Fixture（不存运行时 ID）"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    test_case_id = Column(
        Integer, ForeignKey("test_case.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属测试用例ID",
    )
    fixture_id = Column(
        Integer, ForeignKey("fixture.id", ondelete="RESTRICT"),
        nullable=False, index=True,
        comment="所需 Fixture ID（RESTRICT：被引用时禁止删除）",
    )
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
