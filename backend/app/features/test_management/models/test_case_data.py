"""测试数据（Test Case Data）ORM 模型。

测试数据描述用例执行所需的输入数据项。source_type 决定取值方式：
- STATIC：value 字段即字面值
- ENVIRONMENT：value 为环境键名（base_url/gateway_prefix/default_headers 中的键）
- VARIABLE：value 为变量引用标识，运行期从初始变量解析
- RUNTIME / FAKER / FIXTURE：预留，本阶段不实现自动生成

value_type ∈ {STRING, INTEGER, NUMBER, BOOLEAN, OBJECT, ARRAY}。
required=True 时缺失将导致用例执行失败。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.sql import func, text

from app.core.database.base import Base


class TestCaseData(Base):
    """测试用例数据项。"""

    __tablename__ = "test_case_data"
    __table_args__ = (
        UniqueConstraint("test_case_id", "name", name="uq_test_case_data_case_name"),
        {"comment": "测试用例数据项"},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    test_case_id = Column(
        Integer,
        ForeignKey("test_case.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属测试用例ID",
    )
    name = Column(String(100), nullable=False, comment="数据项名")
    value_type = Column(
        String(20), nullable=False, default="STRING", server_default=text("'STRING'"),
        comment="值类型：STRING/INTEGER/NUMBER/BOOLEAN/OBJECT/ARRAY",
    )
    value = Column(Text, nullable=True, comment="值或引用标识")
    source_type = Column(
        String(20), nullable=False, default="STATIC", server_default=text("'STATIC'"),
        comment="来源：STATIC/ENVIRONMENT/VARIABLE/RUNTIME/FAKER/FIXTURE",
    )
    required = Column(Boolean, nullable=False, default=False, server_default=text("false"), comment="是否必需")
    description = Column(String(500), nullable=True, comment="说明")
    config_json = Column(JSON, nullable=True, comment="附加配置")
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), comment="排序")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
