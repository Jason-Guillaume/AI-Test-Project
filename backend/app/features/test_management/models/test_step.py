"""测试步骤（Test Step）ORM 模型。

测试步骤描述用例的执行编排。step_type 决定步骤职责：
- SETUP：前置准备
- ACTION：核心执行动作（target_type 指向 API/业务流程/业务动作）
- ASSERT：断言（本阶段断言独立于 test_assertion 表，步骤级断言用 config_json）
- CLEANUP：清理

target_type/target_id 指向被测对象；config_json 存放步骤级配置
（如 path_params / headers / query / body 覆盖、超时等）。
"""

from sqlalchemy import Column, DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.sql import func, text

from app.shared.database import Base


class TestStep(Base):
    """测试步骤。"""

    __tablename__ = "test_step"
    __table_args__ = ({"comment": "测试步骤"},)

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    test_case_id = Column(
        Integer,
        ForeignKey("test_case.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属测试用例ID",
    )
    name = Column(String(200), nullable=False, comment="步骤名")
    step_type = Column(
        String(20), nullable=False, default="ACTION", server_default=text("'ACTION'"),
        comment="步骤类型：SETUP/ACTION/ASSERT/CLEANUP",
    )
    target_type = Column(String(20), nullable=True, comment="被测对象类型：API/BUSINESS_FLOW/BUSINESS_ACTION")
    target_id = Column(Integer, nullable=True, comment="被测对象ID")
    sort = Column(Integer, nullable=False, default=0, server_default=text("0"), index=True, comment="排序")
    config_json = Column(JSON, nullable=True, comment="步骤配置（path_params/headers/query/body/timeout 等）")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), comment="创建时间")
    updated_at = Column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now(), comment="更新时间",
    )
