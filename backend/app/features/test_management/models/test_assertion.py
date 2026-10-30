"""断言（Test Assertion）ORM 模型。

断言定义对响应/执行结果的校验。assertion_type 决定取值来源：
- STATUS_CODE：HTTP 状态码
- JSON_PATH：响应体 JSONPath（path 字段，如 $.code）
- HEADER：响应头（source 字段为头名）
- RESPONSE_TIME：响应耗时（毫秒）
- CONTAINS / NOT_CONTAINS：响应体文本包含/不包含

operator ∈ {EQ, NE, GT, GE, LT, LE, IN, EXISTS, NOT_EXISTS}。
source：HEADER 类型时为头名；其余类型可空。
path：JSON_PATH 类型时为 JSONPath 表达式；其余可空。
required=True 时断言失败即用例失败；False 时仅记录不阻断（软断言）。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class TestAssertion(Base):
    """测试断言。"""

    __tablename__ = "test_assertion"
    __table_args__ = ({"comment": "测试断言"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    test_case_id = Column(
        Integer,
        ForeignKey("test_case.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属测试用例ID",
    )
    step_id = Column(
        Integer,
        ForeignKey("test_step.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联步骤ID（可空，空表示用例级断言）",
    )
    assertion_type = Column(
        String(30), nullable=False, default="STATUS_CODE", server_default=text("'STATUS_CODE'"),
        comment="断言类型：STATUS_CODE/JSON_PATH/HEADER/RESPONSE_TIME/CONTAINS/NOT_CONTAINS",
    )
    source = Column(String(100), nullable=True, comment="来源标识：HEADER 名 / CONTEXT 作用域")
    path = Column(String(500), nullable=True, comment="JSONPath 或字段路径（如 $.code）")
    operator = Column(
        String(20), nullable=False, default="EQ", server_default=text("'EQ'"),
        comment="操作符：EQ/NE/GT/GE/LT/LE/IN/EXISTS/NOT_EXISTS",
    )
    expected_value = Column(Text, nullable=True, comment="期望值")
    required = Column(Boolean, nullable=False, default=True, server_default=text("true"), comment="是否必需（软断言=False）")
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
