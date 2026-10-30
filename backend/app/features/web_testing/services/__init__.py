"""Web 测试服务公开入口；通过惰性导出避免与 Agent 探索服务形成导入环。"""

__all__ = ["WebUIService", "generate_draft", "build_target_policy", "mark_session_closed_by_runtime"]


def __getattr__(name):
    """按调用方需要加载门面，底层服务可独立被 Agent 探索能力使用。"""
    if name == "WebUIService":
        from app.features.web_testing.services.web_ui_service import WebUIService
        return WebUIService
    if name == "generate_draft":
        from app.features.web_testing.services.draft_service import generate_draft
        return generate_draft
    if name == "build_target_policy":
        from app.features.web_testing.services.target_policy_service import build_target_policy
        return build_target_policy
    if name == "mark_session_closed_by_runtime":
        from app.features.web_testing.services.runtime_lifecycle_service import mark_session_closed_by_runtime
        return mark_session_closed_by_runtime
    raise AttributeError(name)
