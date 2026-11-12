"""正式 Web 测试资产模型；Agent 探索会话映射由 agents.browser_authoring 持有。"""
from .web_ui import PageObject, WebArtifact, WebAuthProfile, WebCase
from app.agents.models.browser_authoring import WebAgentSession, WebAgentStep

__all__ = ["PageObject", "WebArtifact", "WebAuthProfile", "WebAgentSession", "WebAgentStep", "WebCase"]
