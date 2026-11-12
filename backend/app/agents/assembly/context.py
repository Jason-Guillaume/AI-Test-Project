"""Agent 指令与 Skill 上下文组装。

本模块只组合已冻结的运行快照与静态运行变量；它不授予工具权限、不改变任务状态，
也不把模型凭据写入提示词或任务事件。
"""

from __future__ import annotations

from datetime import datetime
import time
from typing import Any

from app.llm.tracing import record_runtime_span, task_trace_metadata
from app.orchestration.tasks.services.runtime_fact_service import record_runtime_event
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
    rendered_file_count = 0
    started = time.monotonic()
    skill_loads: list[dict[str, Any]] = []
    instruction = render_skill_text(str(profile.get("instruction") or ""), values).strip()
    if instruction:
        sections.append(f"平台配置的 Agent 补充指令：\n{instruction}")
    for skill in profile.get("skills") or []:
        skill_started = time.monotonic()
        name = str(skill.get("name") or skill.get("key") or "Skill")
        try:
            files = load_skill_files(skill)
            rendered_file_count += len(files)
            content = render_skill_text(str(files.get("SKILL.md") or ""), values).strip()
            if content:
                sections.append(f"Skill「{name}」：\n{content}")
            for path, file_content in files.items():
                if path == "SKILL.md" or not str(file_content).strip():
                    continue
                sections.append(f"Skill「{name}」文件 `{path}`：\n{render_skill_text(str(file_content), values).strip()}")
        except Exception as exc:
            runtime = task_trace_metadata.get() or {}
            span_id = record_runtime_span(
                name="skill.load",
                metadata={"skill_key": skill.get("key"), "skill_version": skill.get("version")},
                output={"status": "FAILED", "error_type": type(exc).__name__},
            )
            if runtime.get("project_id"):
                record_runtime_event(
                    project_id=runtime["project_id"], task_id=runtime.get("task_id"),
                    task_run_id=runtime.get("task_run_id"),
                    execution_root_run_id=runtime.get("execution_root_run_id"),
                    work_item_id=runtime.get("work_item_id"), attempt_id=runtime.get("attempt_id"),
                    agent_session_id=runtime.get("agent_session_id"),
                    agent_instance_id=runtime.get("agent_run_id"),
                    agent_definition_id=runtime.get("agent_id"),
                    agent_definition_revision_id=runtime.get("agent_revision_id"),
                    trace_id=runtime.get("trace_id"), span_id=span_id,
                    event_type="SKILL_LOAD", event_name=f"{skill.get('key') or 'unknown'}@{skill.get('version') or 'unknown'}",
                    status="FAILED", error_code=type(exc).__name__,
                    duration_ms=int((time.monotonic() - skill_started) * 1000),
                    event_metadata={"skill_keys": [skill.get("key")] if skill.get("key") else [],
                                    "skill_versions": [skill.get("version")] if skill.get("version") is not None else []},
                )
            raise
        skill_loads.append({
            "key": skill.get("key"), "version": skill.get("version"),
            "file_count": len(files), "duration_ms": int((time.monotonic() - skill_started) * 1000),
        })
    skills = profile.get("skills") or []
    runtime = task_trace_metadata.get() or {}
    span_id = record_runtime_span(
        name="skill.load",
        metadata={"skill_refs": [
            {"key": skill.get("key"), "version": skill.get("version")}
            for skill in skills
        ]},
        output={"loaded_skill_count": len(skills), "rendered_file_count": rendered_file_count,
                "duration_ms": int((time.monotonic() - started) * 1000)},
    )
    if runtime.get("project_id"):
        for skill_load in skill_loads:
            record_runtime_event(
                project_id=runtime["project_id"], task_id=runtime.get("task_id"),
                task_run_id=runtime.get("task_run_id"),
                execution_root_run_id=runtime.get("execution_root_run_id"),
                work_item_id=runtime.get("work_item_id"), attempt_id=runtime.get("attempt_id"),
                agent_session_id=runtime.get("agent_session_id"),
                agent_instance_id=runtime.get("agent_run_id"),
                agent_definition_id=runtime.get("agent_id"),
                agent_definition_revision_id=runtime.get("agent_revision_id"),
                trace_id=runtime.get("trace_id"), span_id=span_id,
                event_type="SKILL_LOAD", event_name=f"{skill_load['key'] or 'unknown'}@{skill_load['version'] if skill_load['version'] is not None else 'unknown'}",
                status="SUCCEEDED", duration_ms=skill_load["duration_ms"],
                event_metadata={"skill_keys": [skill_load["key"]] if skill_load["key"] else [],
                                "skill_versions": [skill_load["version"]] if skill_load["version"] is not None else [],
                                "file_count": skill_load["file_count"]},
            )
    return "\n\n".join(sections)
