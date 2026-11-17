"""统一模型中心隔离回归：项目授权、模型类别与任务参数槽位。"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.core.models
import app.features.api_catalog.models
from app.core.database.base import Base
from app.core.models.identity import User
from app.core.models.project import Project
from app.features.asr_evaluation.models import AsrConnection
from app.features.asr_evaluation.schemas import AudioItemInput, ModelTaskSlotInput
from app.features.asr_evaluation.services.assets_service import create_audio
from app.platform.model_configuration.center_schemas import ModelDiagnosticInput, ModelProfileCreate, ModelResourceCreate
from app.platform.model_configuration.models import ModelCredential, ModelResource, ModelValidationRun
from app.platform.model_configuration.services.model_center_service import (
    create_diagnostic, create_profile, create_resource, list_available_models, preview_import, resolve_task_slots,
)


@pytest.fixture
def center_sandbox():
    """建立只供当前测试使用的内存库和两个互相隔离的项目。"""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    table_prefixes = ("asr_", "model_")
    table_names = {
        "user", "organization", "organization_member", "project", "project_member",
        "project_outbound_target", "model_configuration", "environment", "notification",
        "api_module", "api_interface",
    }
    tables = [table for name, table in Base.metadata.tables.items()
              if name in table_names or name.startswith(table_prefixes)]
    Base.metadata.create_all(engine, tables=tables)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = factory()
    suffix = uuid.uuid4().hex[:10]
    admin = User(username=f"center-admin-{suffix}", role="admin", is_active=True)
    owner_a = User(username=f"center-owner-a-{suffix}", role="test", is_active=True)
    owner_b = User(username=f"center-owner-b-{suffix}", role="test", is_active=True)
    db.add_all([admin, owner_a, owner_b])
    db.flush()
    project_a = Project(name=f"center-a-{suffix}", owner_id=owner_a.id)
    project_b = Project(name=f"center-b-{suffix}", owner_id=owner_b.id)
    db.add_all([project_a, project_b])
    db.commit()
    yield db, admin, owner_a, owner_b, project_a, project_b
    db.close()
    engine.dispose()


def _asr_resource(project_ids: list[int]) -> ModelResourceCreate:
    """构造仅使用已注册通用 JSON ASR 适配器的合成模型配置。"""
    return ModelResourceCreate(
        category="ASR", visibility="PLATFORM", display_name="合成 ASR",
        provider="synthetic-vendor", adapter_key="generic-json-http", model_name="synthetic-asr-v1",
        endpoint="https://asr.example.invalid/v1/recognize", credential="synthetic-secret", credential_header="X-API-Key",
        config={
            "method": "POST", "headers": {},
            "request_template": {"audio_url": "{{audio.url}}", "options": "{{experiment.parameters}}"},
            "response_mapping": {"text_pointer": "/text"},
            "timeout_seconds": 3, "max_response_bytes": 2048,
        },
        capabilities=["transcription"],
        parameter_schema=[{"path": "/language", "display_name": "识别语言", "value_type": "string"}],
        initial_profile={"name": "中文基线", "values": {"language": "zh"},
                         "definitions": [{"path": "/language", "display_name": "识别语言", "value_type": "string"}]},
        grant_project_ids=project_ids,
    )


def _text_resource() -> ModelResourceCreate:
    return ModelResourceCreate(
        category="TEXT_GENERATION", visibility="PLATFORM", display_name="合成文本模型",
        provider="synthetic-vendor", adapter_key="openai-compatible-chat", model_name="synthetic-text-v1",
        endpoint="https://models.example.invalid/v1/chat/completions", config={"timeout": 3},
        capabilities=["text_generation"],
        initial_profile={"name": "文本基线", "values": {"temperature": 0}, "definitions": []},
    )


def _diarization_resource() -> ModelResourceCreate:
    return ModelResourceCreate(
        category="DIARIZATION", visibility="PLATFORM", display_name="合成说话人模型",
        provider="synthetic-vendor", adapter_key="generic-json-http", model_name="synthetic-diarization-v1",
        endpoint="https://models.example.invalid/v1/diarize", config={
            "method": "POST", "headers": {}, "request_template": {
                "audio_url": "{{audio.url}}", "options": "{{experiment.parameters}}",
            },
            "response_mapping": {"segments_pointer": "/segments", "start_pointer": "/segments/0/start",
                                  "end_pointer": "/segments/0/end", "speaker_pointer": "/segments/0/speaker",
                                  "time_unit": "seconds"},
            "timeout_seconds": 3, "max_response_bytes": 2048,
        },
        capabilities=["speaker_intervals"],
        initial_profile={"name": "说话人基线", "values": {"language": "zh"}, "definitions": []},
    )


def test_diagnostic_schema_requires_project_and_explicit_paid_call_confirmation():
    with pytest.raises(ValidationError):
        ModelDiagnosticInput(project_id=0, confirm_model_call=True)
    with pytest.raises(ValidationError):
        ModelDiagnosticInput(project_id=1, confirm_model_call=False)


def test_text_diagnostic_queues_for_selected_editor_project_without_calling_provider(center_sandbox):
    db, admin, owner_a, _, project_a, _ = center_sandbox
    resource = create_resource(db, _text_resource(), admin)
    run = create_diagnostic(db, resource["id"], ModelDiagnosticInput(
        project_id=project_a.id, confirm_model_call=True,
    ), owner_a)
    stored = db.query(ModelValidationRun).filter_by(id=run["id"]).one()
    assert run["status"] == "QUEUED"
    assert stored.project_id == project_a.id and stored.audio_id is None


@pytest.mark.parametrize("category", ["ASR", "DIARIZATION"])
def test_audio_diagnostic_enforces_project_audio_ownership_and_editor_access(center_sandbox, category):
    db, admin, owner_a, owner_b, project_a, project_b = center_sandbox
    body = _asr_resource([]) if category == "ASR" else _diarization_resource()
    resource = create_resource(db, body, admin)
    audio_a = create_audio(db, project_a.id, AudioItemInput(name="项目 A 音频", url="https://audio.example.test/a.wav"), owner_a)
    audio_b = create_audio(db, project_b.id, AudioItemInput(name="项目 B 音频", url="https://audio.example.test/b.wav"), owner_b)
    profile_id = resource["current_revision"]["profiles"][0]["id"]

    run = create_diagnostic(db, resource["id"], ModelDiagnosticInput(
        project_id=project_a.id, audio_id=audio_a["id"], profile_id=profile_id, confirm_model_call=True,
    ), owner_a)
    assert run["status"] == "QUEUED"
    with pytest.raises(HTTPException) as wrong_audio:
        create_diagnostic(db, resource["id"], ModelDiagnosticInput(
            project_id=project_a.id, audio_id=audio_b["id"], profile_id=profile_id, confirm_model_call=True,
        ), owner_a)
    assert wrong_audio.value.status_code == 404
    with pytest.raises(HTTPException) as wrong_project:
        create_diagnostic(db, resource["id"], ModelDiagnosticInput(
            project_id=project_a.id, audio_id=audio_a["id"], profile_id=profile_id, confirm_model_call=True,
        ), owner_b)
    assert wrong_project.value.status_code == 404


def test_platform_models_need_no_grant_and_role_is_a_task_slot(center_sandbox):
    """共享 ASR 启用即全项目可用；实验角色仍是任务槽位。"""
    db, admin, owner_a, owner_b, project_a, project_b = center_sandbox
    created = create_resource(db, _asr_resource([project_a.id]), admin)
    resource = db.query(ModelResource).filter_by(id=created["id"]).one()
    credential = db.query(ModelCredential).filter_by(revision_id=resource.current_revision_id).one()
    assert credential.ciphertext != "synthetic-secret"
    assert created["current_revision"]["has_credential"] is True
    assert "synthetic-secret" not in str(created)
    revision = resource.current_revision_id
    from app.platform.model_configuration.models import ModelParameterProfile

    baseline = db.query(ModelParameterProfile).filter_by(resource_id=resource.id).one()
    tuned = create_profile(db, resource.id, ModelProfileCreate(
        revision_id=revision, name="夜间降噪", values={"language": "zh", "noise_reduction": True},
        definitions=[],
    ), admin)

    available_a = list_available_models(db, project_id=project_a.id, category="ASR", actor=owner_a)
    available_b = list_available_models(db, project_id=project_b.id, category="ASR", actor=owner_b)
    assert [item["id"] for item in available_a["items"]] == [resource.id]
    assert [item["id"] for item in available_b["items"]] == [resource.id]

    selected_test = resolve_task_slots(db, project_a.id, [ModelTaskSlotInput(
        slot="TEST", resource_id=resource.id, revision_id=revision, profile_id=baseline.id,
    )], owner_a)[0]
    selected_reference = resolve_task_slots(db, project_a.id, [ModelTaskSlotInput(
        slot="REFERENCE_A", resource_id=resource.id, revision_id=revision, profile_id=tuned["id"],
    )], owner_a)[0]
    assert selected_test["resource"].id == selected_reference["resource"].id == resource.id
    assert selected_test["profile"].id != selected_reference["profile"].id
    assert selected_test["connection"].id == selected_reference["connection"].id
    assert selected_test["connection"].role is None
    assert selected_test["connection"].project_id == project_a.id
    db.commit()

    with pytest.raises(Exception, match="所选项目模型或参数方案不可用"):
        resolve_task_slots(db, project_a.id, [ModelTaskSlotInput(
            slot="DIARIZATION", resource_id=resource.id, revision_id=revision, profile_id=baseline.id,
        )], owner_a)
    assert db.query(AsrConnection).filter_by(project_id=project_a.id).count() == 1

    with pytest.raises(HTTPException) as exc_info:
        create_profile(db, resource.id, ModelProfileCreate(
            revision_id=revision, name="非法密钥参数", values={"api_key": "must-not-be-profile-data"}, definitions=[],
        ), admin)
    assert "凭据" in exc_info.value.detail


def test_unregistered_adapter_is_rejected_instead_of_advertised(center_sandbox):
    """新增供应商名不能绕过协议适配器注册表。"""
    db, admin, _, _, project_a, _ = center_sandbox
    body = _asr_resource([project_a.id]).model_copy(update={"adapter_key": "signed-vendor-adapter"})
    with pytest.raises(HTTPException) as exc_info:
        create_resource(db, body, admin)
    assert exc_info.value.detail == "该类别尚未实现所选调用适配器"
    assert db.query(ModelResource).count() == 0


def test_siliconflow_resource_projects_multipart_config_and_encrypted_credential(center_sandbox):
    db, admin, owner, _, project, _ = center_sandbox
    body = ModelResourceCreate(
        category="ASR", visibility="PLATFORM",
        display_name="星辰 ASR", provider="siliconflow", adapter_key="siliconflow-audio-transcriptions",
        model_name="XingChenAGI/XingChenASR-V3.2", endpoint="https://api.siliconflow.cn/v1/audio/transcriptions",
        credential="synthetic-key", credential_header="Authorization", config={}, capabilities=["transcription"],
    )
    created = create_resource(db, body, admin)
    revision = created["current_revision"]
    assert revision["config"]["request_encoding"] == "multipart"
    assert revision["has_credential"]
    assert "synthetic-key" not in str(created)
    selected = resolve_task_slots(db, project.id, [ModelTaskSlotInput(
        slot="TEST", resource_id=created["id"], revision_id=revision["id"], profile_id=revision["profiles"][0]["id"],
    )], owner)[0]
    assert selected["connection"].config_json["request_encoding"] == "multipart"
    assert selected["connection"].secret_ciphertext != "synthetic-key"


def test_model_center_connection_can_queue_single_model_transcription(center_sandbox):
    from app.features.asr_evaluation.models import AsrAudio, AsrModelRun, AsrWorkItem
    from app.features.asr_evaluation.schemas import ConnectionCheck
    from app.features.asr_evaluation.services.assets_service import create_audio
    from app.features.asr_evaluation.schemas import AudioItemInput
    from app.features.asr_evaluation.services.job_service import create_connection_check

    db, admin, owner, _, project, _ = center_sandbox
    body = _asr_resource([])
    created = create_resource(db, body, admin)
    revision = created['current_revision']
    connection = resolve_task_slots(db, project.id, [ModelTaskSlotInput(
        slot='TEST', resource_id=created['id'], revision_id=revision['id'], profile_id=revision['profiles'][0]['id'],
    )], owner)[0]['connection']
    assert connection.role is None
    audio = create_audio(db, project.id, AudioItemInput(name="识别音频", url="https://audio.example.test/probe.wav"), owner)
    job = create_connection_check(db, connection.id, ConnectionCheck(audio_id=audio["id"]), owner)
    run = db.query(AsrModelRun).filter_by(job_id=job["id"]).one()
    assert run.role == "TEST" and run.status == "PENDING"
    assert run.request_snapshot["role"] == "TEST"
    assert connection.role is None
    assert db.query(AsrWorkItem).filter_by(run_id=run.id).count() == 1


def test_import_preview_rejects_nested_secret_fields_without_echoing_values(center_sandbox):
    """导入预检递归拒绝敏感字段，并且错误文案不回显其值。"""
    db, admin, _, _, _, _ = center_sandbox
    result = preview_import(db, [{
        "display_name": "合成导入", "config": {"headers": {"Authorization": "Bearer private-secret"}},
    }], admin)
    assert result["can_apply"] is False
    assert result["items"][0]["errors"] == ["预检文件不能包含凭据，请在模型中心单独录入"]
    assert "private-secret" not in str(result)
