"""回归：目录兼容处理器不能被误报为统一任务执行器。"""

from __future__ import annotations

import pytest

from app.tools.registry import ToolDispatchError, get_binding, runtime_capability


@pytest.mark.parametrize(
    "key",
    ["business.list_flows", "test_asset.save_cases", "web_ui.generate_draft"],
)
def test_catalog_only_handlers_are_not_reported_as_runnable(key: str) -> None:
    capability = runtime_capability(key)

    assert capability["catalog_status"] == "catalog_only"
    assert capability["handler_registered"] is True
    assert capability["executor_registered"] is False
    assert capability["allowed_channels"] == []
    with pytest.raises(ToolDispatchError):
        get_binding(key, channel="model")


def test_active_tool_reports_its_unified_executor_channel() -> None:
    capability = runtime_capability("api_catalog.search_api")

    assert capability["catalog_status"] == "active"
    assert capability["executor_registered"] is True
    assert capability["allowed_channels"]
