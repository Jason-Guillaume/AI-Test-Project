"""Web UI 专属模型；仅由 0012 迁移建表，不加入基线模型注册。"""
from .web_ui import PageObject, WebArtifact, WebAuthProfile, WebCase

__all__ = ["PageObject", "WebArtifact", "WebAuthProfile", "WebCase"]
