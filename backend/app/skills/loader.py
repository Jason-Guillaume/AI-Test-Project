"""Skill 文件树加载器。

统一读取数据库 Skill 与历史任务快照中的文本文件映射；不在文件系统创建第二份数据库内容源，
也不执行 ZIP 内代码。调用方继续由 Agent 组装器检查版本、启用状态和长度限制。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def load_skill_files(skill: Any) -> dict[str, str]:
    """从 ORM 对象或历史快照读取文件树，并兼容只含旧 ``content`` 的记录。"""
    if isinstance(skill, Mapping):
        content = str(skill.get("content") or "")
        files = skill.get("files_json") or {}
    else:
        content = str(getattr(skill, "content", "") or "")
        files = getattr(skill, "files_json", None) or {}
    result = {str(path): str(text) for path, text in files.items()}
    if not result.get("SKILL.md") and content:
        result["SKILL.md"] = content
    return result
