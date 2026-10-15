"""Data Provider 注册表。

两套类型名并存，这里统一收敛：
- ``FixtureStep.step_type``：FIXTURE / API / BUSINESS_ACTION / BUSINESS_FLOW / FAKER /
  STATIC / DATABASE_INSERT / DATABASE_PATCH，以及只保存不执行的预留类型
  WAIT / DATABASE_QUERY / EXTERNAL_PROVIDER。
- ``DataProvider.provider_type``：STATIC / ENVIRONMENT / FAKER / API_CREATE /
  BUSINESS_ACTION / BUSINESS_FLOW / EXISTING_POOL / DATABASE_INSERT / DATABASE_PATCH。

步骤优先引用 ``provider_id``（配置落在 Provider 行上）；没有引用时按 ``step_type``
找到对应类型，用步骤自己的 ``config_json``。``FIXTURE`` 不是 Provider——它是「先跑
另一个 Fixture」，由 ``runtime/data_factory.py`` 递归处理。
"""

from __future__ import annotations

from app.features.test_data.providers.api_create_provider import ApiCreateProvider
from app.features.test_data.providers.base import (
    CLEANUP_HANDLE_KEY,
    RESPONSE_BODY_KEY,
    STATUS_FAILED,
    STATUS_SUCCESS,
    BaseProvider,
    ProviderContext,
    ProviderResult,
    config_of,
    run_safe,
)
from app.features.test_data.providers.business_action_provider import BusinessActionProvider
from app.features.test_data.providers.business_flow_provider import BusinessFlowProvider
from app.features.test_data.providers.database_provider import DatabaseProvider
from app.features.test_data.providers.environment_provider import EnvironmentProvider
from app.features.test_data.providers.faker_provider import FakerProvider
from app.features.test_data.providers.pool_provider import PoolProvider
from app.features.test_data.providers.static_provider import StaticProvider

#: step_type → provider_type。API 步骤对应 API_CREATE；DATABASE_* 同名直连。
STEP_TYPE_TO_PROVIDER_TYPE: dict[str, str] = {
    "API": "API_CREATE",
    "BUSINESS_ACTION": "BUSINESS_ACTION",
    "BUSINESS_FLOW": "BUSINESS_FLOW",
    "FAKER": "FAKER",
    "STATIC": "STATIC",
    "DATABASE_INSERT": "DATABASE_INSERT",
    "DATABASE_PATCH": "DATABASE_PATCH",
}

#: 可执行的 step_type（含 FIXTURE：递归，不算 Provider）。
EXECUTABLE_STEP_TYPES = frozenset({"FIXTURE", *STEP_TYPE_TO_PROVIDER_TYPE.keys()})

#: 只保存不执行；执行到即 FIXTURE_STEP_UNSUPPORTED。
RESERVED_STEP_TYPES = frozenset({"WAIT", "DATABASE_QUERY", "EXTERNAL_PROVIDER"})

#: 实例注册表：Provider 都是无状态的，进程级单例复用。
PROVIDER_REGISTRY: dict[str, BaseProvider] = {
    "STATIC": StaticProvider(),
    "ENVIRONMENT": EnvironmentProvider(),
    "FAKER": FakerProvider(),
    "API_CREATE": ApiCreateProvider(),
    "BUSINESS_ACTION": BusinessActionProvider(),
    "BUSINESS_FLOW": BusinessFlowProvider(),
    "EXISTING_POOL": PoolProvider(),
    "DATABASE_INSERT": DatabaseProvider(),
    "DATABASE_PATCH": DatabaseProvider(),
}


def provider_for_step_type(step_type: str | None, provider_type: str | None = None) -> BaseProvider | None:
    """按 Provider 类型（优先）或步骤类型返回 Provider 实例；未知类型返回 None。"""
    key = provider_type or STEP_TYPE_TO_PROVIDER_TYPE.get(step_type or "")
    return PROVIDER_REGISTRY.get(key) if key else None


__all__ = [
    "CLEANUP_HANDLE_KEY",
    "EXECUTABLE_STEP_TYPES",
    "PROVIDER_REGISTRY",
    "RESPONSE_BODY_KEY",
    "RESERVED_STEP_TYPES",
    "STATUS_FAILED",
    "STATUS_SUCCESS",
    "STEP_TYPE_TO_PROVIDER_TYPE",
    "provider_for_step_type",
    "run_safe",
    "BaseProvider",
    "ProviderContext",
    "ProviderResult",
    "ApiCreateProvider",
    "BusinessActionProvider",
    "BusinessFlowProvider",
    "DatabaseProvider",
    "EnvironmentProvider",
    "FakerProvider",
    "PoolProvider",
    "StaticProvider",
    "config_of",
]
