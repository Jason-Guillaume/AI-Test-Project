"""Agent 指令与 Skill 上下文组装。

本模块只组合已冻结的运行快照与静态运行变量；它不授予工具权限、不改变任务状态，
也不把模型凭据写入提示词或任务事件。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.skills.loader import load_skill_files
from app.skills.renderer import render_skill_text


def build_agent_guidance(profile: dict[str, Any] | None) -> str:
    """渲染运行快照中的 Agent 指令、Skill 入口文件和附属文本。"""
    profile = profile or {}
    settings = profile.get("settings_json") or {}
    values = {
        "Now": datetime.now().astimezone().isoformat(timespec="seconds"),
        "DataDir": "任务运行时数据目录",
    }
    for variable in settings.get("runtime_variables") or []:
        name = str(variable.get("name") or "").strip()
        if name and name not in values:
            # 自定义变量只允许静态文本，避免把配置解释成表达式。
            values[name] = str(variable.get("value") or "")

    sections: list[str] = []
    instruction = render_skill_text(str(profile.get("instruction") or ""), values).strip()
    if instruction:
        sections.append(f"平台配置的 Agent 补充指令：\n{instruction}")
    for skill in profile.get("skills") or []:
        name = str(skill.get("name") or skill.get("key") or "Skill")
        files = load_skill_files(skill)
        content = render_skill_text(str(files.get("SKILL.md") or ""), values).strip()
        if content:
            sections.append(f"Skill「{name}」：\n{content}")
        for path, file_content in files.items():
            if path == "SKILL.md" or not str(file_content).strip():
                continue
            sections.append(f"Skill「{name}」文件 `{path}`：\n{render_skill_text(str(file_content), values).strip()}")
    return "\n\n".join(sections)
