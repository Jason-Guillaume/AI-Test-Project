"""测试管理 ORM 模型集合（feature-local）。

延续 business / api_catalog 约定：模型**不**加入 app/models/__init__.py，
由 alembic/versions/0006_create_test_tables.py 用显式 op.create_table 建立，
避免与 0001 的 Base.metadata.create_all 冲突。运行期由路由→服务→模型导入链触发加载，
注册进 Base.metadata 供 ORM 查询使用。

建表顺序遵循外键依赖（见 0006 迁移 _TABLES_IN_ORDER）。
所有资产表预留 source_type 字段，为未来 source_type=AI（Agent 生成）留位，
但本阶段不接入 LLM / LangGraph / Agent。
"""

from app.features.test_management.models.execution import CaseExecution, TestRun
from app.features.test_management.models.test_assertion import TestAssertion
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.models.test_case_data import TestCaseData
from app.features.test_management.models.test_case_precondition import TestCasePrecondition
from app.features.test_management.models.test_plan import TestPlan, TestPlanSuite
from app.features.test_management.models.test_point import TestPoint
from app.features.test_management.models.test_step import TestStep
from app.features.test_management.models.test_strategy import TestStrategy
from app.features.test_management.models.test_suite import TestSuite, TestSuiteCase

__all__ = [
    "TestCase",
    "TestCaseData",
    "TestCasePrecondition",
    "TestAssertion",
    "TestPlan",
    "TestPlanSuite",
    "TestPoint",
    "TestRun",
    "CaseExecution",
    "TestStep",
    "TestStrategy",
    "TestSuite",
    "TestSuiteCase",
]
