"""Web UI 生成工具适配器。

把稳定工具标识转发给 Web UI 功能的公开服务，不实现浏览器运行或人工确认流程。
"""
from app.features.web_testing.services import generate_draft
from app.tools.registry import bind_module_handlers

bind_module_handlers(globals(), {
    "generate_draft": ("web_ui.generate_draft", "write"),
})
