"""Skill 文本变量渲染。

保留既有 ``{{.Name}}`` 静态替换语法，不求值表达式、不执行文件内容；
运行长度限制在 Agent 组装时按现有总 Skill 上限检查。
"""

from __future__ import annotations

from collections.abc import Mapping


def render_skill_text(content: str, values: Mapping[str, str]) -> str:
    """按既有变量语法替换一段 Skill 文本，不改变未知变量。"""
    rendered = content
    for name, value in values.items():
        rendered = rendered.replace("{{." + name + "}}", value)
    return rendered
