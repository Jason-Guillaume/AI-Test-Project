"""Skill 定义、文件树、版本与使用统计服务。

内容和附属文本继续保存在数据库快照中；MCP 关联只表示依赖，调用授权仍由 MCP 运行服务复核。
"""
from __future__ import annotations
import io
import re
import stat
import uuid
import zipfile
from typing import Any
from sqlalchemy.orm import Session
from app.skills.schemas import SkillCreate, SkillUpdate
from app.skills.models import SkillDefinition, SkillDefinitionRevision, SkillUsageEvent
from app.mcp.models import MCPServer
from app.core.http.errors import bad_request, not_found


def _skill_snapshot(row: SkillDefinition) -> dict[str, Any]:
    """生成技能定义的版本快照。"""
    return {
        "name": row.name,
        "description": row.description,
        "content": row.content,
        "is_enabled": row.is_enabled,
        "files_json": row.files_json or {"SKILL.md": row.content},
        "mcp_tool_keys_json": row.mcp_tool_keys_json or [],
    }

def list_skills(db: Session) -> list[SkillDefinition]:
    """列出`skills`。"""
    return db.query(SkillDefinition).order_by(SkillDefinition.updated_at.desc(), SkillDefinition.id.desc()).all()

def create_skill(db: Session, body: SkillCreate, actor_id: int) -> SkillDefinition:
    """创建`skill`。"""
    values = body.model_dump()
    files = values.pop("files_json") or {"SKILL.md": values["content"]}
    if "SKILL.md" not in files:
        files["SKILL.md"] = values["content"]
    values["content"] = files["SKILL.md"]
    _validate_skill_mcp_links(db, values["mcp_tool_keys_json"])
    row = SkillDefinition(key=str(uuid.uuid4()), files_json=files, **values, created_by=actor_id, updated_by=actor_id)
    db.add(row)
    db.flush()
    db.add(SkillDefinitionRevision(
        skill_definition_id=row.id,
        version=row.version,
        snapshot_json=_skill_snapshot(row),
        created_by=actor_id,
    ))
    db.commit()
    db.refresh(row)
    return row

def import_skill_zip(db: Session, archive_bytes: bytes, filename: str, actor_id: int, *, name: str | None = None) -> SkillDefinition:
    """导入只读文本型 Agent Skill 压缩包，拒绝路径穿越与可执行文件。"""
    if not archive_bytes or len(archive_bytes) > 2_000_000:
        raise bad_request("Skill ZIP 必须小于 2 MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except (zipfile.BadZipFile, OSError) as exc:
        raise bad_request("上传文件不是有效的 ZIP 压缩包") from exc
    with archive:
        members = [item for item in archive.infolist() if not item.is_dir()]
        if len(members) > 200:
            raise bad_request("Skill ZIP 最多包含 200 个文件")
        files: dict[str, str] = {}
        total = 0
        for item in members:
            path = item.filename.replace("\\", "/")
            parts = path.split("/")
            mode = (item.external_attr >> 16) & 0xFFFF
            if path.startswith("/") or any(part in {"", ".", ".."} for part in parts) or stat.S_ISLNK(mode):
                raise bad_request("Skill ZIP 包含不安全的文件路径")
            if parts[0] == "__MACOSX" or parts[-1] == ".DS_Store":
                continue
            if path.rsplit(".", 1)[-1].lower() not in {"md", "txt", "json", "yaml", "yml", "toml", "xml", "csv"}:
                raise bad_request(f"Skill 只能导入文本文件：{parts[-1]}")
            if item.file_size > 100_000 or total + item.file_size > 1_000_000:
                raise bad_request("Skill ZIP 解压后单文件不能超过 100 KB，总大小不能超过 1 MB")
            try:
                with archive.open(item) as compressed:
                    raw_content = compressed.read(100_001)
                    if len(raw_content) > 100_000 or compressed.read(1):
                        raise bad_request("Skill ZIP 单文件解压内容超过 100 KB")
                content = raw_content.decode("utf-8")
            except (UnicodeDecodeError, RuntimeError, zipfile.BadZipFile) as exc:
                raise bad_request(f"Skill 文件不是有效 UTF-8 文本：{parts[-1]}") from exc
            total += len(content.encode("utf-8"))
            files[path] = content
    if "SKILL.md" not in files:
        prefix = next(iter(files), "").split("/", 1)[0]
        if prefix and all(path.startswith(prefix + "/") for path in files):
            files = {path[len(prefix) + 1:]: content for path, content in files.items()}
    if "SKILL.md" not in files:
        raise bad_request("ZIP 根目录必须包含 SKILL.md")
    resolved_name = (name or "").strip() or filename.rsplit(".", 1)[0][:120] or "导入的 Skill"
    description = ""
    for line in files["SKILL.md"].splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            description = line.strip()[:2000]
            break
    return create_skill(db, SkillCreate(
        name=resolved_name,
        description=description,
        content=files["SKILL.md"],
        files_json=files,
        is_enabled=False,
    ), actor_id)

def update_skill(db: Session, skill_id: int, body: SkillUpdate, actor_id: int) -> SkillDefinition:
    """更新`skill`。"""
    row = db.get(SkillDefinition, skill_id)
    if row is None:
        raise not_found("Skill 不存在")
    changes = {key: value for key, value in body.model_dump(exclude_unset=True).items() if value is not None}
    if "files_json" in changes:
        files = changes["files_json"]
        if "SKILL.md" not in files:
            raise bad_request("Skill 文件树必须包含 SKILL.md")
        changes["content"] = files["SKILL.md"]
    elif "content" in changes:
        changes["files_json"] = {**(row.files_json or {}), "SKILL.md": changes["content"]}
    _validate_skill_mcp_links(db, changes.get("mcp_tool_keys_json", row.mcp_tool_keys_json or []))
    if changes:
        for key, value in changes.items():
            setattr(row, key, value)
        row.version += 1
        row.updated_by = actor_id
        db.add(SkillDefinitionRevision(
            skill_definition_id=row.id,
            version=row.version,
            snapshot_json=_skill_snapshot(row),
            created_by=actor_id,
        ))
        db.commit()
        db.refresh(row)
    return row

def skill_versions(db: Session, skill_id: int) -> list[SkillDefinitionRevision]:
    """列出技能定义的历史版本。"""
    if db.get(SkillDefinition, skill_id) is None:
        raise not_found("Skill 不存在")
    return db.query(SkillDefinitionRevision).filter(
        SkillDefinitionRevision.skill_definition_id == skill_id
    ).order_by(SkillDefinitionRevision.version.desc()).all()

def remove_skill(db: Session, skill_id: int) -> None:
    """删除`skill`。"""
    row = db.get(SkillDefinition, skill_id)
    if row is None:
        raise not_found("Skill 不存在")
    db.delete(row)
    db.commit()

def restore_skill_version(db: Session, skill_id: int, version: int, actor_id: int) -> SkillDefinition:
    """将历史 Skill 快照恢复为当前配置，并新建版本。"""
    revision = db.query(SkillDefinitionRevision).filter_by(skill_definition_id=skill_id, version=version).first()
    if revision is None:
        raise not_found("Skill 历史版本不存在")
    allowed = {"name", "description", "content", "is_enabled", "files_json", "mcp_tool_keys_json"}
    body = SkillUpdate.model_validate({key: value for key, value in revision.snapshot_json.items() if key in allowed})
    return update_skill(db, skill_id, body, actor_id)

def _validate_skill_mcp_links(db: Session, keys: list[str]) -> None:
    if len(set(keys)) != len(keys):
        raise bad_request("Skill 关联的 MCP 工具不能重复")
    for key in keys:
        match = re.fullmatch(r"mcp:(\d+):(.+)", key)
        if not match:
            raise bad_request("Skill 只能关联 MCP 工具")
        server = db.get(MCPServer, int(match.group(1)))
        tool_name = match.group(2)
        discovered = {item.get("name"): item for item in (server.discovered_tools_json or [])} if server else {}
        tool = discovered.get(tool_name)
        if server is None or tool_name not in (server.approved_tools_json or []) or tool is None:
            raise bad_request("Skill 只能关联已发现并审批的 MCP 工具")
        if (tool.get("annotations") or {}).get("readOnlyHint") is not True:
            raise bad_request("Skill 关联的 MCP 工具必须明确标记为只读")



def validate_skill_mcp_links(db: Session, keys: list[str]) -> None:
    """公开 Skill 的 MCP 依赖校验入口，保留只读审批要求。"""
    _validate_skill_mcp_links(db, keys)
