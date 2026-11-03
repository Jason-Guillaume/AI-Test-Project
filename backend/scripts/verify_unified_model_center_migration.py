"""在临时 SQLite 数据库验证 0034 对 0033 数据的前向与回退迁移。"""

from __future__ import annotations

import os
import json
import sys
import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
EXCLUDED_CENTER_TABLES = {
    "model_resource", "model_revision", "model_credential", "model_parameter_profile",
    "model_legacy_binding", "model_resource_grant", "model_default_binding",
    "model_validation_run", "model_task_slot",
}


def _prepare_legacy_schema(database_url: str) -> tuple[int, list[int], int, int, int]:
    """以 0033 时的 ORM 表创建旧结构，并插入可验证旧引用的合成行。"""
    os.environ["DATABASE_URL"] = database_url
    import app.core.models
    from app.core.database.base import Base
    from app.core.models.configuration import ModelConfiguration
    from app.core.models.identity import User
    from app.core.models.project import Project
    from app.features.asr_evaluation.models import AsrConnection, AsrJob, AsrParameterSet, AsrSchedule
    from app.platform.model_configuration import models as center_models  # noqa: F401

    core_tables = {
        "user", "organization", "organization_member", "project", "project_member",
        "project_outbound_target", "model_configuration", "environment", "notification",
    }
    tables = [table for name, table in Base.metadata.tables.items()
              if name not in EXCLUDED_CENTER_TABLES and (name in core_tables or name.startswith("asr_"))]
    engine = create_engine(database_url)
    Base.metadata.create_all(engine, tables=tables)
    with Session(engine) as db:
        actor = User(username="migration-check", role="admin", is_active=True)
        db.add(actor)
        db.flush()
        project = Project(name="migration-check-project", owner_id=actor.id)
        db.add(project)
        db.flush()
        text_model = ModelConfiguration(
            domain_id="model-migration-check", label="兼容文本模型", provider="openai-compatible",
            api_base="https://text.example.invalid/v1", api_key_encrypted="legacy-ciphertext",
            model_name="synthetic-text", temperature=0.25, max_tokens=321, timeout=40,
            is_enabled=True, is_default=True, fallback_model_ids=[], sort_order=0, created_by=actor.id,
        )
        db.add(text_model)
        db.flush()
        connections = []
        for role, name in (("TEST", "测试连接"), ("REFERENCE", "参考 A"), ("REFERENCE", "参考 B")):
            connection = AsrConnection(
                project_id=project.id, name=name, role=role, task_type="TRANSCRIPTION",
                provider_id="generic-json", model_id="synthetic-asr", version=1,
                endpoint_ciphertext="legacy-endpoint-ciphertext", endpoint_display="https://asr.example.invalid/run",
                config_json={"request_template": {}, "response_mapping": {"text_pointer": "/text"}},
                secret_ciphertext=None, enabled=True, created_by=actor.id,
            )
            db.add(connection)
            connections.append(connection)
        db.flush()
        profile = AsrParameterSet(
            project_id=project.id, connection_id=connections[0].id, name="旧待测参数", version=3,
            parameters={"language": "zh"}, definitions=[], created_by=actor.id,
        )
        db.add(profile)
        db.flush()
        snapshot_connections = [
            {"id": item.id, "role": item.role, "name": item.name, "model_id": item.model_id}
            for item in connections
        ]
        job = AsrJob(
            project_id=project.id, status="QUEUED", created_by=actor.id,
            config_snapshot={
                "connections": snapshot_connections,
                "parameter_set": {"id": profile.id, "name": profile.name, "version": profile.version},
            },
        )
        db.add(job)
        schedule = AsrSchedule(
            project_id=project.id, name="迁移检查计划", audio_ids=[],
            connection_ids=[item.id for item in connections], parameter_set_id=profile.id,
            schedule_type="DAILY", timezone="Asia/Shanghai", local_time="01:00",
            enabled=True, created_by=actor.id,
        )
        db.add(schedule)
        db.commit()
        result = (text_model.id, [item.id for item in connections], profile.id, job.id, schedule.id)
    engine.dispose()
    return result


def _migrate(database_url: str, direction: str) -> None:
    """在给定临时库上运行指定 Alembic 转换。"""
    os.environ["DATABASE_URL"] = database_url
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    if direction == "stamp":
        command.stamp(config, "0033")
    elif direction == "upgrade":
        command.upgrade(config, "0034")
    else:
        command.downgrade(config, "0033")


def _assert_migrated(database_url: str, old_ids: tuple[int, list[int], int, int, int]) -> None:
    """验证旧 ID、默认语义、参数值及任务槽位被完整保留。"""
    text_id, connection_ids, parameter_id, job_id, schedule_id = old_ids
    engine = create_engine(database_url)
    with engine.connect() as connection:
        row = connection.execute(text(
            "SELECT r.resource_key, r.legacy_model_id, p.parameter_values FROM model_resource r "
            "JOIN model_parameter_profile p ON p.resource_id=r.id WHERE r.legacy_model_id=:id"
        ), {"id": text_id}).mappings().one()
        assert row["resource_key"] == "model-migration-check"
        assert row["legacy_model_id"] == text_id
        defaults = connection.execute(text(
            "SELECT category, purpose FROM model_default_binding WHERE resource_id=("
            "SELECT id FROM model_resource WHERE legacy_model_id=:id)"
        ), {"id": text_id}).mappings().all()
        assert [(item["category"], item["purpose"]) for item in defaults] == [("TEXT_GENERATION", "TEXT_INFERENCE")]
        parameter_values = row["parameter_values"]
        if isinstance(parameter_values, str):
            parameter_values = json.loads(parameter_values)
        assert parameter_values["temperature"] == 0.25
        slots = connection.execute(text(
            "SELECT task_kind, task_id, slot, legacy_connection_id, profile_id FROM model_task_slot "
            "WHERE task_id IN (:job_id, :schedule_id) ORDER BY task_kind, slot"
        ), {"job_id": job_id, "schedule_id": schedule_id}).mappings().all()
        assert len(slots) == 6
        assert {item["legacy_connection_id"] for item in slots} == set(connection_ids)
        assert {item["slot"] for item in slots} == {"TEST", "REFERENCE_A", "REFERENCE_B"}
        test_slot = next(item for item in slots if item["task_kind"] == "ASR_JOB" and item["slot"] == "TEST")
        profile_binding = connection.execute(text(
            "SELECT id FROM model_parameter_profile WHERE legacy_parameter_set_id=:id"
        ), {"id": parameter_id}).scalar_one()
        assert test_slot["profile_id"] == profile_binding
    engine.dispose()


def main() -> None:
    """创建并删除专用临时库，不读取或修改开发数据库。"""
    handle, path = tempfile.mkstemp(prefix="unified-model-center-", suffix=".sqlite", dir="/private/tmp")
    os.close(handle)
    database_url = "sqlite:///" + path
    try:
        old_ids = _prepare_legacy_schema(database_url)
        _migrate(database_url, "stamp")
        _migrate(database_url, "upgrade")
        _assert_migrated(database_url, old_ids)
        _migrate(database_url, "downgrade")
        _migrate(database_url, "upgrade")
        _assert_migrated(database_url, old_ids)
        print("0034 SQLite 前向迁移、回退再升级验证通过；旧 ID、默认、参数与任务槽位完整。")
    finally:
        Path(path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
