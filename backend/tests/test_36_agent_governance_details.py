"""Agent / Skill 详情配置的持久化、版本恢复与安全导入回归。"""

from __future__ import annotations

import io
import zipfile

from tests.conftest import unique


def _agent_payload(name: str) -> dict:
    return {
        "name": name,
        "description": "Governance detail test",
        "workflow_template": "api_test",
        "instruction": "只在授权范围内工作。",
        "model_config_id": None,
        "skill_keys": [],
        "tool_keys": [],
        "child_agent_ids": [],
        "is_enabled": False,
        "settings_json": {
            "max_loop_count": 7,
            "timeout_seconds": 240,
            "close_step_prompt": "总结已核对的证据。",
            "runtime_variables": [{"name": "Now", "value": "{{.Now}}"}],
        },
        "triggers_json": [{
            "id": "created-trigger",
            "event": "task.created",
            "enabled": False,
            "message": "开始执行已确认的目标",
            "queue_policy": "serial",
            "coalesce_by": "task",
            "max_concurrency": 1,
        }],
    }


def test_agent_detail_settings_are_versioned_and_restorable(api, admin):
    created = api.post("/agent-governance/agents", username=admin, json=_agent_payload(unique("detail-agent")))
    assert created.status_code == 201, created.text
    original = created.json()
    assert original["settings_json"]["max_loop_count"] == 7
    assert original["triggers_json"][0]["event"] == "task.created"

    update = api.patch(
        f"/agent-governance/agents/{original['id']}",
        username=admin,
        json={"settings_json": {"max_loop_count": 3, "timeout_seconds": 600}, "instruction": "更新后的提示词"},
    )
    assert update.status_code == 200, update.text
    assert update.json()["version"] == original["version"] + 1
    assert update.json()["settings_json"]["max_loop_count"] == 3

    restored = api.post(
        f"/agent-governance/agents/{original['id']}/versions/{original['version']}/restore",
        username=admin,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["version"] == original["version"] + 2
    assert restored.json()["settings_json"]["max_loop_count"] == 7
    assert restored.json()["instruction"] == "只在授权范围内工作。"

    history = api.get(f"/agent-governance/agents/{original['id']}/versions", username=admin)
    assert history.status_code == 200
    assert [item["version"] for item in history.json()] == [3, 2, 1]


def test_legacy_model_config_requests_keep_fixed_binding_semantics(api, admin):
    from tests.test_04_admin_authorization import MODEL_CONFIG_PAYLOAD

    model = api.post(
        "/model-configs",
        username=admin,
        json={**MODEL_CONFIG_PAYLOAD, "domain_id": unique("legacy-agent-model")},
    )
    assert model.status_code == 201, model.text
    payload = _agent_payload(unique("legacy-model-agent"))
    payload.pop("settings_json")
    payload["model_config_id"] = model.json()["id"]
    created = api.post("/agent-governance/agents", username=admin, json=payload)
    assert created.status_code == 201, created.text
    assert created.json()["settings_json"]["model_binding"] == "agent"

    cleared = api.patch(
        f"/agent-governance/agents/{created.json()['id']}",
        username=admin,
        json={"model_config_id": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["model_config_id"] is None
    assert cleared.json()["settings_json"]["model_binding"] == "task_or_global"


def test_tool_detail_binding_disable_and_restore(api, admin):
    created = api.post("/agent-governance/agents", username=admin, json=_agent_payload(unique("tool-agent")))
    assert created.status_code == 201, created.text
    agent = created.json()
    tool_key = "api_catalog.search_api"
    catalog = api.get("/agent-governance/tools", username=admin)
    assert catalog.status_code == 200, catalog.text
    tool_detail = next(item for item in catalog.json() if item["key"] == tool_key)
    assert tool_detail["runtime_details"]["status"] == "active"
    assert tool_detail["runtime_details"]["runtime_name"] == "api-catalog.search"
    assert {item["name"] for item in tool_detail["runtime_details"]["input_context"]} == {"project_id", "api_ids"}

    bound = api.put(
        f"/agent-governance/tools/{tool_key}",
        username=admin,
        json={
            "description": "在项目授权范围内检索接口目录。",
            "agent_ids": [agent["id"]],
            "parameter_overrides_json": {"api_ids": {"description": "只列出此任务已确认关联的接口。"}},
            "is_enabled": True,
        },
    )
    assert bound.status_code == 200, bound.text
    assert bound.json()["agent_ids"] == [agent["id"]]
    assert bound.json()["runtime_details"]["output"].startswith("项目内接口名称")
    api_ids = next(item for item in bound.json()["runtime_details"]["input_context"] if item["name"] == "api_ids")
    assert api_ids["description"] == "只列出此任务已确认关联的接口。"

    invalid_override = api.put(
        f"/agent-governance/tools/{tool_key}",
        username=admin,
        json={
            "description": "不能写入不存在的参数。",
            "agent_ids": [agent["id"]],
            "parameter_overrides_json": {"made_up_argument": {"description": "不存在"}},
            "is_enabled": True,
        },
    )
    assert invalid_override.status_code == 400, invalid_override.text

    rows = api.get("/agent-governance/tools", username=admin).json()
    assert next(item for item in rows if item["key"] == tool_key)["description"] == "在项目授权范围内检索接口目录。"

    disabled = api.put(
        f"/agent-governance/tools/{tool_key}",
        username=admin,
        json={"description": "停用检查", "agent_ids": [agent["id"]], "parameter_overrides_json": {}, "is_enabled": False},
    )
    assert disabled.status_code == 200, disabled.text
    assert disabled.json()["is_enabled"] is False
    assert disabled.json()["agent_ids"] == []

    restored = api.post(f"/agent-governance/tools/{tool_key}/restore-defaults", username=admin)
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_enabled"] is True
    assert restored.json()["agent_ids"] == []


def test_skill_file_tree_versions_usage_and_zip_import(api, admin):
    created = api.post(
        "/agent-governance/skills",
        username=admin,
        json={
            "name": unique("file-skill"),
            "description": "文件型 Skill",
            "content": "# Review\n检查证据。",
            "files_json": {"SKILL.md": "# Review\n检查证据。", "references/checklist.md": "逐项核对。"},
            "mcp_tool_keys_json": [],
            "is_enabled": False,
        },
    )
    assert created.status_code == 201, created.text
    skill = created.json()
    assert skill["files_json"]["references/checklist.md"] == "逐项核对。"

    updated = api.patch(
        f"/agent-governance/skills/{skill['id']}",
        username=admin,
        json={"files_json": {"SKILL.md": "# Updated\n更新的规则。", "notes.md": "附加内容"}},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["content"] == "# Updated\n更新的规则。"
    assert updated.json()["version"] == skill["version"] + 1

    restored = api.post(
        f"/agent-governance/skills/{skill['id']}/versions/{skill['version']}/restore",
        username=admin,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["files_json"]["references/checklist.md"] == "逐项核对。"
    assert restored.json()["version"] == skill["version"] + 2

    usage = api.get(f"/agent-governance/skills/{skill['id']}/usage", username=admin)
    assert usage.status_code == 200, usage.text
    assert usage.json()["total_loads"] == 0

    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("imported/SKILL.md", "# Imported\nImported guidance.")
        archive.writestr("imported/references/example.md", "Example content.")
    imported = api.post(
        "/agent-governance/skills/import-zip",
        username=admin,
        files={"file": ("skill.zip", archive_buffer.getvalue(), "application/zip")},
        data={"name": unique("zip-skill")},
    )
    assert imported.status_code == 201, imported.text
    assert set(imported.json()["files_json"]) == {"SKILL.md", "references/example.md"}
    assert imported.json()["is_enabled"] is False


def test_skill_zip_rejects_path_traversal(api, admin):
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("SKILL.md", "# Unsafe")
        archive.writestr("../outside.md", "must not be extracted")
    response = api.post(
        "/agent-governance/skills/import-zip",
        username=admin,
        files={"file": ("unsafe.zip", archive_buffer.getvalue(), "application/zip")},
    )
    assert response.status_code == 400, response.text


def test_agent_runtime_variable_preview_matches_task_guidance():
    from app.features.tasks.models.task import TaskRun
    from app.features.tasks.runtime.worker import _agent_guidance

    run = TaskRun(input_snapshot={
        "agent_definition": {
            "instruction": "现在是 {{.Now}}，目录 {{.DataDir}}，环境 {{.EnvName}}。",
            "settings_json": {"runtime_variables": [{"name": "EnvName", "value": "测试环境"}]},
            "skills": [{"name": "规则", "files_json": {"SKILL.md": "执行 {{.EnvName}} 检查。", "notes.md": "目录 {{.DataDir}}"}}],
        },
    })
    rendered = _agent_guidance(run)
    assert "{{.Now}}" not in rendered
    assert "{{.DataDir}}" not in rendered
    assert "{{.EnvName}}" not in rendered
    assert "测试环境" in rendered
    assert "任务运行时数据目录" in rendered
