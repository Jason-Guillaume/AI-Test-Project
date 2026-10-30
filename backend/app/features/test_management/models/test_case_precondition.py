"""测试用例前置条件（Test Case Precondition）ORM 模型。

描述用例执行前必须满足的条件。type 决定评估方式：
- VARIABLE：校验运行时变量（复用 precondition_evaluator 语义）
- TEXT / FIXTURE / API / BUSINESS_ACTION / BUSINESS_FLOW：本阶段标记为需人工确认（passed=True）

operator ∈ {EQ, NE, GT, GE, LT, LE, IN, EXISTS, NOT_EXISTS, CONTAINS}。
config_json 存放附加配置（如 fixture 标识、引用路径等）。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class TestCasePrecondition(Base):
    """测试用例前置条件。"""

    __tablename__ = "test_case_precondition"
    __table_args__ = ({"comment": "测试用例前置条件"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    test_case_id = Column(
        Integer,
        ForeignKey("test_case.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属测试用例ID",
    )
    type = Column(
        String(30), nullable=False, default="VARIABLE", server_default=text("'VARIABLE'"),
        comment="前置条件类型：VARIABLE/TEXT/FIXTURE/API/BUSINESS_ACTION/BUSINESS_FLOW",
    )
    target = Column(String(200), nullable=True, comment="目标：变量名/实体/说明")
    operator = Column(
        String(20), nullable=False, default="EQ", server_default=text("'EQ'"),
        comment="操作符：EQ/NE/GT/GE/LT/LE/IN/EXISTS/NOT_EXISTS/CONTAINS",
    )
    expected_value = Column(Text, nullable=True, comment="期望值")
    description = Column(String(500), nullable=True, comment="说明")
    config_json = Column(JSON, nullable=True, comment="附加配置")
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
