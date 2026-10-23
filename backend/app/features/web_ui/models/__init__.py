"""Web UI 专属模型；仅由 0012/0014 迁移建表，不加入基线模型注册。"""
from .web_ui import PageObject, WebArtifact, WebAuthProfile, WebAgentSession, WebAgentStep, WebCase

__all__ = ["PageObject", "WebArtifact", "WebAuthProfile", "WebAgentSession", "WebAgentStep", "WebCase"]
