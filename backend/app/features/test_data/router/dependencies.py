"""本领域路由使用的无状态服务装配；不拥有请求事务。"""

from __future__ import annotations

from app.features.test_data.services.asset_service import AssetService
from app.features.test_data.services.connection_service import ConnectionService, PolicyService
from app.features.test_data.services.execution_query_service import ExecutionQueryService
from app.features.test_data.services.fixture_service import FixtureService
from app.features.test_data.services.pool_service import PoolService
from app.features.test_data.services.provider_service import ProviderService
from app.features.test_data.services.runtime_service import RuntimeService


_FIXTURE = FixtureService()


_ASSET = AssetService()


_PROVIDER = ProviderService()


_POOL = PoolService()


_CONNECTION = ConnectionService()


_POLICY = PolicyService()


_EXECUTION = ExecutionQueryService()


_RUNTIME = RuntimeService()
