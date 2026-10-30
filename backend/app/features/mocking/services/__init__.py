"""Mock Management 服务层。

管理服务保留原事务边界；项目可见性与写入校验由本包公开的 access_service 契约提供。
执行面由 ``MockRuntimeService`` 单独承担，与管理面共享同一组模型和访问规则。
"""

from __future__ import annotations

from app.features.mocking.services.access_service import (
    require_manage_project,
    resolve_service_project_id,
    resolve_endpoint_project_id,
    resolve_scenario_project_id,
    resolve_execution_project_id,
)
from app.features.mocking.services.agent_catalog_service import (
    find_scenario_for_api,
    get_mock_scenario,
    list_mock_scenarios,
    list_mock_services,
)

