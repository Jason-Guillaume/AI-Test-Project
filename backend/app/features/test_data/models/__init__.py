"""测试数据中心 ORM 模型（feature-local 导出）。

只在本 feature 内导出，**不**加入 app/models/__init__.py（红线 17）。
表由 alembic/versions/0009_test_data_center.py 显式建表，应用启动不 create_all。

注意：这些模型被 import 后才会进入 `Base.metadata`。任何依赖 metadata 完整性的
逻辑（如 AUTO_CREATE_SCHEMA=true 的本地调试 create_all）需要先 import 本模块。
"""

from app.features.test_data.models.asset import TestDataAsset
from app.features.test_data.models.case_fixture import TestCaseFixture
from app.features.test_data.models.connection import (
    DatabaseAccessPolicy,
    TargetDatabaseConnection,
)
from app.features.test_data.models.execution import (
    DataExecution,
    FixtureCache,
    FixtureExecution,
    ProviderExecution,
)
from app.features.test_data.models.fixture import (
    Fixture,
    FixtureDependency,
    FixtureOutput,
    FixtureStep,
)
from app.features.test_data.models.pool import DataPool, DataPoolItem, DataPoolLease
from app.features.test_data.models.provider import DataProvider

__all__ = [
    "DataProvider",
    "DataExecution",
    "DatabaseAccessPolicy",
    "DataPool",
    "DataPoolItem",
    "DataPoolLease",
    "Fixture",
    "FixtureCache",
    "FixtureDependency",
    "FixtureExecution",
    "FixtureOutput",
    "FixtureStep",
    "ProviderExecution",
    "TargetDatabaseConnection",
    "TestCaseFixture",
    "TestDataAsset",
]
