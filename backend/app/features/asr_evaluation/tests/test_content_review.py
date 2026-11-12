"""内容评审分块、证据及后台队列的隔离合成回归，不访问真实模型。"""

import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException

from app.core.config import settings
from app.core.database.base import Base
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import OrganizationMember, User
from app.core.models.project import Project, ProjectMember
from app.features.asr_evaluation.models import AsrContentReviewJob, AsrDiffBlock, AsrModelRun
from app.features.asr_evaluation.services.content_review_planning import plan_chunks, speaker_mapping, validate_result
from app.features.asr_evaluation.services.content_review_service import (
    claim_review, create_review, execute_review, get_review, list_review_models, list_reviews, recover_expired_reviews, retry_review, review_summary,
)
from app.features.asr_evaluation.services.comparison_service import record_run_result, run_experiment
from app.features.asr_evaluation.tests.test_regressions import sandbox
from app.features.asr_evaluation.tests.test_candidate_rerun import _comparison_for_center
from app.platform.model_configuration.tests.test_model_center import center_sandbox
from app.llm.contracts import LLMError


def test_chunk_plan_keeps_long_text_and_real_time():
    """超长段不丢失文字，拆分后仍只引用原段真实时间。"""
    text = "中😀" * 2000
    chunks = plan_chunks([{"run_id": 1, "transcript": text, "segments": [{"evidence_id": "run:1:segment:1",
        "text": text, "start_ms": 100, "end_ms": 2000, "start_offset": 0, "end_offset": len(text)}]}])
    pieces = [item for chunk in chunks for item in chunk["evidence"]]
    assert "".join(item["text"] for item in pieces) == text
    assert all(item["start_ms"] == 100 and item["end_ms"] == 2000 for item in pieces)


def test_worker_can_pause_review_claims_without_stopping_asr(monkeypatch):
    """关闭评审开关后仍检查 ASR 队列，但绝不领取新的评审任务。"""
    import app.features.asr_evaluation.runtime.worker as worker_module
    monkeypatch.setattr(settings, "ASR_CONTENT_REVIEW_ENABLED", False)
    worker = worker_module.AsrWorker(poll_seconds=0.1)
    asr_checks = []
    monkeypatch.setattr(worker, "_business_dependencies_ready", lambda: True)
    for name in ("_process_due_schedules", "_recover_expired_suggestions", "_recover_expired_reviews", "_recover_pending_artifacts"):
        monkeypatch.setattr(worker, name, lambda: None)
    monkeypatch.setattr(worker, "_claim_next", lambda: asr_checks.append(True))
    monkeypatch.setattr(worker, "_claim_next_processing", lambda _kind: None)
    monkeypatch.setattr(worker, "_claim_next_suggestion", lambda: None)
    monkeypatch.setattr(worker, "_write_heartbeat", lambda **_kwargs: worker.stop())
    monkeypatch.setattr(worker_module, "claim_review", lambda *_args: pytest.fail("暂停时不得领取评审"))
    worker.run_forever()
    assert asr_checks == [True]


def test_time_context_includes_long_running_segment_and_marks_budget_overflow():
    """长时间片段跨多个窗口时仍作为对照；上下文超限必须显式标记。"""
    long_text = "长" * 12000
    snapshots = [
        {"run_id": 1, "transcript": long_text, "segments": [{"evidence_id": "long", "text": long_text,
         "start_ms": 0, "end_ms": 100000, "start_offset": 0}]},
        {"run_id": 2, "transcript": "后段", "segments": [{"evidence_id": "later", "text": "后段",
         "start_ms": 65000, "end_ms": 66000, "start_offset": 0}]},
    ]
    chunks = plan_chunks(snapshots)
    later = next(chunk for chunk in chunks if chunk["scope"]["window_start_ms"] == 60000)
    assert any(item["evidence_id"] == "long" and item.get("context_only") for item in later["evidence"])
    assert later["scope"]["context_incomplete"] is True


def test_rejects_wrong_or_ambiguous_evidence():
    """不属于输入的引句和同片段重复引句不得进入报告。"""
    chunk = {"evidence": [{"evidence_id": "a", "run_id": 1, "text": "重复重复", "piece_offset": 0,
                           "start_offset": 0, "start_ms": 0, "end_ms": 100}]}
    for quote in ("不存在", "重复"):
        with pytest.raises(ValueError):
            validate_result({"verdict": "reviewed", "findings": [{"description": "观察", "evidence": [{"id": "a", "quote": quote}]}]}, chunk, "SINGLE")


def test_comparison_rejects_single_source_claim():
    """比较结论不能只引用一侧文本。"""
    chunk = {"evidence": [{"evidence_id": "a", "run_id": 1, "text": "基线文本", "piece_offset": 0,
                           "start_offset": 0, "start_ms": None, "end_ms": None, "native_speaker_id": None}]}
    with pytest.raises(ValueError, match="多个来源"):
        validate_result({"verdict": "candidate_better", "findings": [{"description": "候选更清晰",
            "evidence": [{"id": "a", "quote": "基线"}]}]}, chunk, "AB")


def test_single_review_executes_fake_model_and_saves_evidence(sandbox, tmp_path, monkeypatch):
    """任务完整冻结、保存实际输入和回复并验证证据，不触发 ASR。"""
    db, _, actor, _, _, _, job = sandbox
    monkeypatch.setattr(settings, "ASR_ARTIFACT_DIR", str(tmp_path))
    run = db.query(AsrModelRun).filter_by(job_id=job["id"]).first()
    run.status, run.transcript = "SUCCEEDED", "这是合成文本。"
    model = ModelConfiguration(domain_id="synthetic-review", label="合成模型", provider="openai-compatible",
        api_base="https://example.invalid", model_name="synthetic", is_enabled=True, created_by=actor.id)
    db.add(model)
    db.commit()
    result = create_review(db, "SINGLE", run.id, model.id, actor)
    assert create_review(db, "SINGLE", run.id, model.id, actor)["id"] == result["id"]
    claim = claim_review(db, "synthetic")

    class FakeProvider:
        """不访问网络的合成内容模型。"""
        def __init__(self, *_args, **_kwargs):
            pass

        def chat(self, _system, _content):
            return json.dumps({"verdict": "reviewed", "findings": [{"dimension": "可读性", "description": "句子完整。",
                "evidence": [{"id": f"run:{run.id}:transcript", "quote": "合成文本"}]}]}, ensure_ascii=False)

    import app.llm.providers.openai_compatible as provider_module
    monkeypatch.setattr(provider_module, "ProductionLLMProvider", FakeProvider)
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    execute_review(*claim, session_factory=factory)
    db.expire_all()
    result = get_review(db, result["id"], actor)
    assert result["status"] == "SUCCEEDED", result
    assert result["coverage_status"] == "COMPLETE"
    assert result["covered_evidence"] == result["total_evidence"] > 0
    assert result["report_artifact_id"]
    assert result["chunks"][0]["input_artifact_id"] and result["chunks"][0]["response_artifact_id"]
    assert result["chunks"][0]["result"]["findings"][0]["evidence"][0]["quote"] == "合成文本"
    listing = list_reviews(db, "run", run.id, actor)
    assert listing["total"] == 1 and listing["items"][0]["chunks"] == []


def test_expired_review_never_replays(sandbox, tmp_path, monkeypatch):
    """租约过期进入待核实，不重新领取并产生第二次计费。"""
    db, _, actor, _, _, _, job = sandbox
    monkeypatch.setattr(settings, "ASR_ARTIFACT_DIR", str(tmp_path))
    run = db.query(AsrModelRun).filter_by(job_id=job["id"]).first()
    run.status, run.transcript = "SUCCEEDED", "合成文本"
    model = ModelConfiguration(domain_id="synthetic-expired-review", label="合成模型", provider="openai-compatible",
        api_base="https://example.invalid", model_name="synthetic", is_enabled=True, created_by=actor.id)
    db.add(model)
    db.commit()
    review = create_review(db, "SINGLE", run.id, model.id, actor)
    claim_review(db, "expired")
    row = db.get(AsrContentReviewJob, review["id"])
    row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert recover_expired_reviews(db) == 1
    assert get_review(db, row.id, actor)["status"] == "RECONCILIATION_REQUIRED"
    assert claim_review(db, "other") is None


def test_no_time_alignment_preserves_each_transcript():
    """缺失时间时使用有界文本对齐，保留各侧 Unicode 偏移与全文。"""
    texts = ["甲😀。乙。", "甲😀。新增。乙。", "甲😀。乙。"]
    chunks = plan_chunks([{"run_id": index + 1, "transcript": text, "segments": []} for index, text in enumerate(texts)])
    for index, text in enumerate(texts):
        pieces = [item for chunk in chunks for item in chunk["evidence"] if item["run_id"] == index + 1]
        assert "".join(piece["text"] for piece in pieces) == text
        assert all(piece["start_ms"] is None for piece in pieces)


def test_speaker_label_swap_uses_time_mapping_and_keeps_ambiguity():
    """标签编号交换时按时间建立唯一对应；没有时间时保持不确定。"""
    snapshots = [
        {"run_id": 1, "segments": [{"native_speaker_id": "spk_0", "start_ms": 0, "end_ms": 1000},
                                  {"native_speaker_id": "spk_1", "start_ms": 2000, "end_ms": 3000}]},
        {"run_id": 2, "segments": [{"native_speaker_id": "spk_1", "start_ms": 0, "end_ms": 1000},
                                  {"native_speaker_id": "spk_0", "start_ms": 2000, "end_ms": 3000}]},
    ]
    result = speaker_mapping(snapshots)
    assert {(item["left_label"], item["right_label"]) for item in result["pairs"]} == {("spk_0", "spk_1"), ("spk_1", "spk_0")}
    assert speaker_mapping([{"run_id": 1, "segments": []}, {"run_id": 2, "segments": []}])["status"] == "AMBIGUOUS"


def test_uncertain_second_chunk_is_not_retried(sandbox, tmp_path, monkeypatch):
    """部分块完成后连接状态未知时保留部分覆盖并禁止重试。"""
    db, _, actor, _, _, _, job = sandbox
    monkeypatch.setattr(settings, "ASR_ARTIFACT_DIR", str(tmp_path))
    run = db.query(AsrModelRun).filter_by(job_id=job["id"]).first()
    run.status, run.transcript = "SUCCEEDED", "甲" * 12000
    model = ModelConfiguration(domain_id="synthetic-review-uncertain", label="合成模型", provider="openai-compatible",
        api_base="https://example.invalid", model_name="synthetic", is_enabled=True, created_by=actor.id)
    db.add(model)
    db.commit()
    review = create_review(db, "SINGLE", run.id, model.id, actor)
    assert review["total_chunks"] > 1
    claim = claim_review(db, "worker")

    class FakeProvider:
        """第一块完成，第二块模拟外部传输状态未知。"""
        calls = 0
        def __init__(self, *_args, **_kwargs):
            pass
        def chat(self, *_args):
            FakeProvider.calls += 1
            if FakeProvider.calls == 2:
                raise LLMError("LLM_TRANSPORT_ERROR", "合成超时")
            return '{"verdict":"inconclusive","findings":[]}'

    import app.llm.providers.openai_compatible as provider_module
    monkeypatch.setattr(provider_module, "ProductionLLMProvider", FakeProvider)
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    execute_review(*claim, session_factory=factory)
    db.expire_all()
    result = get_review(db, review["id"], actor)
    assert result["status"] == "RECONCILIATION_REQUIRED"
    assert result["coverage_status"] == "PARTIAL"
    assert result["completed_chunks"] == 1
    assert result["covered_evidence"] < result["total_evidence"]
    assert any(chunk["uncovered_evidence"] for chunk in result["chunks"])
    with pytest.raises(Exception):
        retry_review(db, review["id"], actor)
    assert claim_review(db, "other") is None


def test_triplet_and_candidate_ab_reuse_existing_runs(center_sandbox, tmp_path, monkeypatch):
    """三方和 A/B 分别固定同一音频版本的现有运行，不改变基线。"""
    db, actor, _project, source_job, comparison, experiment, _ = _comparison_for_center(center_sandbox)
    monkeypatch.setattr(settings, "ASR_ARTIFACT_DIR", str(tmp_path))
    model = ModelConfiguration(domain_id="synthetic-ab-review", label="合成模型", provider="openai-compatible",
        api_base="https://example.invalid", model_name="synthetic", is_enabled=True, created_by=actor.id)
    db.add(model)
    db.commit()
    triplet = create_review(db, "TRIPLET", comparison.id, model.id, actor)
    assert len(triplet["run_ids"]) == 3
    assert review_summary(db, source_job["id"], actor)["review_active"] == 1
    candidate = run_experiment(db, experiment["id"], actor)["job"]
    for run in db.query(AsrModelRun).filter_by(job_id=candidate["id"]).all():
        record_run_result(db, run.id, status="SUCCEEDED", transcript="候选合成文本。", segments=[])
    ab = create_review(db, "AB", experiment["id"], model.id, actor)
    assert len(ab["run_ids"]) == 2 and ab["run_ids"][0] in triplet["run_ids"]
    assert review_summary(db, source_job["id"], actor)["ab_denominator"] == 1
    class FakeProvider:
        """三方及候选实验均执行合成评审，保留不能判断的真实语义。"""
        def __init__(self, *_args, **_kwargs):
            pass

        def chat(self, *_args):
            return '{"verdict":"inconclusive","findings":[]}'

    import app.llm.providers.openai_compatible as provider_module
    monkeypatch.setattr(provider_module, "ProductionLLMProvider", FakeProvider)
    factory = sessionmaker(bind=db.get_bind(), autoflush=False, expire_on_commit=False)
    for expected_id in (triplet["id"], ab["id"]):
        claim = claim_review(db, "synthetic-comparison-worker")
        assert claim[0] == expected_id
        execute_review(*claim, session_factory=factory)
        db.expire_all()
        result = get_review(db, expected_id, actor)
        assert result["status"] == "SUCCEEDED" and result["report_artifact_id"]
        assert all(chunk["result"]["verdict"] == "inconclusive" for chunk in result["chunks"])
    assert review_summary(db, source_job["id"], actor)["review_active"] == 0
    assert review_summary(db, source_job["id"], actor)["ab_verdicts"]["inconclusive"] == 1
    block = db.query(AsrDiffBlock).filter_by(comparison_id=comparison.id).first()
    assert block is not None
    block.review_version += 1
    db.commit()
    assert create_review(db, "TRIPLET", comparison.id, model.id, actor)["id"] != triplet["id"]


def test_review_is_hidden_from_other_project_users(sandbox, tmp_path, monkeypatch):
    """评审详情、列表和创建均沿用项目权限，越权返回 404。"""
    db, _, actor, _, _, _, job = sandbox
    monkeypatch.setattr(settings, "ASR_ARTIFACT_DIR", str(tmp_path))
    run = db.query(AsrModelRun).filter_by(job_id=job["id"]).first()
    run.status, run.transcript = "SUCCEEDED", "隔离文本"
    model = ModelConfiguration(domain_id="review-isolation", label="合成模型", provider="openai-compatible",
        api_base="https://example.invalid", model_name="synthetic", is_enabled=True, created_by=actor.id)
    outsider = User(username="review-outsider", role="dev", is_active=True)
    db.add_all([model, outsider])
    db.commit()
    review = create_review(db, "SINGLE", run.id, model.id, actor)
    for action in (lambda: get_review(db, review["id"], outsider),
                   lambda: list_reviews(db, "run", run.id, outsider),
                   lambda: create_review(db, "SINGLE", run.id, model.id, outsider)):
        with pytest.raises(HTTPException) as error:
            action()
        assert error.value.status_code == 404
    run.status = "FAILED"
    db.commit()
    with pytest.raises(HTTPException) as error:
        create_review(db, "SINGLE", run.id, model.id, outsider)
    assert error.value.status_code == 404


def test_member_sees_only_authorized_text_models(sandbox):
    """普通项目成员只看到组织授权并启用的文本模型，不需要平台管理员接口。"""
    db, _, admin, audio, _, _, _ = sandbox
    project = db.get(Project, audio.project_id)
    user = User(username="review-member", role="dev", is_active=True)
    allowed = ModelConfiguration(domain_id="review-allowed", label="允许模型", provider="openai-compatible",
        api_base="https://example.invalid", model_name="allowed", is_enabled=True, created_by=admin.id)
    hidden = ModelConfiguration(domain_id="review-hidden", label="未授权模型", provider="openai-compatible",
        api_base="https://example.invalid", model_name="hidden", is_enabled=True, created_by=admin.id)
    db.add_all([user, allowed, hidden])
    db.flush()
    db.add(OrganizationMember(organization_id=project.organization_id, user_id=user.id, role="member",
                              agent_enabled=True, allowed_model_ids=[allowed.domain_id]))
    db.add(ProjectMember(project_id=project.id, user_id=user.id, role="member", created_by=admin.id))
    db.commit()
    items = list_review_models(db, project.id, user)["items"]
    assert [item["id"] for item in items] == [allowed.id]
    assert set(items[0]) == {"id", "label", "model_name"}


def test_model_revision_checked_before_network(monkeypatch):
    """排队后模型配置变化时不发请求，也不产生未知计费。"""
    from app.llm.providers.openai_compatible import ProductionLLMProvider
    provider = ProductionLLMProvider(object(), model_config_id=1, expected_revision="old")
    monkeypatch.setattr(provider, "_load_config", lambda _id: SimpleNamespace(revision="new", model_name="fake"))
    monkeypatch.setattr(provider, "_post", lambda *_args, **_kwargs: pytest.fail("版本不一致时不得发送"))
    with pytest.raises(LLMError) as error:
        provider.chat("指令", "合成内容")
    assert error.value.code == "MODEL_REVISION_CHANGED"


def test_new_migrations_upgrade_and_downgrade_in_isolated_sqlite(sandbox, monkeypatch):
    """在隔离测试库执行新增两版迁移和回退，不连接开发或业务库。"""
    db = sandbox[0]
    engine = db.get_bind()
    db.close()
    def load_migration(filename):
        """按测试库中的仓库路径加载迁移，不依赖 alembic 包搜索路径。"""
        path = Path(__file__).resolve().parents[4] / "alembic" / "versions" / filename
        spec = importlib.util.spec_from_file_location(filename, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    first = load_migration("0037_asr_evaluation_artifacts.py")
    second = load_migration("0038_asr_content_review.py")
    with engine.begin() as connection:
        for name in ("asr_content_review_chunk", "asr_content_review_job", "asr_evaluation_artifact"):
            Base.metadata.tables[name].drop(connection)
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(first, "op", operations)
        monkeypatch.setattr(second, "op", operations)
        first.upgrade()
        second.upgrade()
        assert {"asr_evaluation_artifact", "asr_content_review_job", "asr_content_review_chunk"}.issubset(inspect(connection).get_table_names())
        second.downgrade()
        first.downgrade()
        assert "asr_evaluation_artifact" not in inspect(connection).get_table_names()
