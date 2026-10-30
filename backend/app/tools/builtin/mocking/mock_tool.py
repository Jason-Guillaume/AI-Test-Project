"""Agent Tool 层：将 Mock 查询映射到安全白名单服务。"""

from app.features.mocking.services.agent_catalog_service import (
    find_scenario_for_api, get_mock_scenario, list_mock_scenarios, list_mock_services,
)

from app.tools.registry import bind_module_handlers

bind_module_handlers(globals(), {
    'list_mock_services': ('runtime.mock_management.list_mock_services', 'read'),
    'list_mock_scenarios': ('runtime.mock_management.list_mock_scenarios', 'read'),
    'get_mock_scenario': ('runtime.mock_management.get_mock_scenario', 'read'),
    'find_scenario_for_api': ('runtime.mock_management.find_scenario_for_api', 'read'),
})
