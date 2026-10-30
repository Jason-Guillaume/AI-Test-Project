"""按业务领域组织的受控内置工具实现。"""

from importlib import import_module

_MODULES = {
    "api_catalog_tool": "app.tools.builtin.api_catalog.api_catalog_tool",
    "business_tool": "app.tools.builtin.business.business_tool",
    "test_asset_tool": "app.tools.builtin.test_management.test_asset_tool",
    "execution_tool": "app.tools.builtin.test_management.execution_tool",
    "fixture_tool": "app.tools.builtin.test_data.fixture_tool",
    "mock_tool": "app.tools.builtin.mocking.mock_tool",
    "security_tool": "app.tools.builtin.security_testing.security_tool",
    "zap_scan_tool": "app.tools.builtin.security_testing.zap_scan_tool",
    "web_ui_tool": "app.tools.builtin.web_testing.web_ui_tool",
    "report_tool": "app.tools.builtin.reports.report_tool",
    "notification_tool": "app.tools.builtin.notifications.notification_tool",
}

__all__ = list(_MODULES)


def __getattr__(name: str):
    """仅从固定领域模块映射中按需加载工具，不接受任意导入路径。"""
    module_name = _MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name)
    globals()[name] = module
    return module
