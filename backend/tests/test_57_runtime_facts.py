"""运行事实白名单元数据测试。"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.core.models.configuration import ModelConfiguration
from app.core.models.identity import User
from app.llm.contracts import LLMError
from app.orchestration.tasks.models import RuntimeCallFact, Task, TaskAttempt, TaskRun, TaskWorkItem
from app.orchestration.tasks.services.state_service import sync_task_status
from app.orchestration.tasks.services.runtime_fact_service import (
    _execution_root_filter, _model_success_rate, _safe_metadata, _skill_identity,
    _task_run_status_metrics, _task_run_window_filter, assert_token_quota,
    model_revision_admitted, runtime_overview,
)
from tests.conftest import unique


def test_runtime_event_metadata_keeps_ids_and_drops_free_text():
    """仅保留预设关联字段，过滤 Prompt、查询正文和任意敏感键。"""
    result = _safe_metadata({
        "query_sha256": "a" * 64,
        "chunk_ids": [11, 12],
        "input_field_names": ["requirements", "count"],
        "query": "不要写入的原始查询",
        "prompt": "不要写入的提示词",
        "api_key": "不要写入的密钥",
        "nested": {"secret": "不要写入的嵌套数据"},
    })

    assert result == {
        "query_sha256": "a" * 64,
        "chunk_ids": [11, 12],
        "input_field_names": ["requirements", "count"],
    }


def test_runtime_event_metadata_bounds_ids_and_strings():
    """关联列表和字符串均有上限，避免异常输入膨胀事实表。"""
    result = _safe_metadata({
        "model_name": "m" * 300,
        "message_ids": list(range(150)),
    })

    assert result["model_name"] == "m" * 200
    assert len(result["message_ids"]) == 100


def test_skill_event_name_keeps_key_and_revision():
    """Skill 运行统计以具体 Revision 分组。"""
    assert _skill_identity("security-review@4") == ("security-review", 4)
    assert _skill_identity("legacy-skill") == ("legacy-skill", None)


def test_task_run_rates_exclude_reconciliation_and_separate_cancellation():
    """待核对不冒充失败；各比例共享含取消的终态分母并披露未完成量。"""
    result = _task_run_status_metrics({
        "SUCCEEDED": 3,
        "SUCCEEDED_WITH_ISSUES": 2,
        "FAILED": 1,
        "CANCELLED": 2,
        "RECONCILIATION_REQUIRED": 4,
        "QUEUED": 3,
        "SUPERSEDED": 1,
    })

    assert result == {
        "task_runs": 16,
        "terminal_runs": 8,
        "successful_runs": 3,
        "partial_runs": 2,
        "failed_runs": 1,
        "cancelled_runs": 2,
        "reconciliation_required_runs": 4,
        "superseded_runs": 1,
        "nonterminal_runs": 3,
        "success_rate": 0.375,
        "partial_completion_rate": 0.25,
        "failure_rate": 0.125,
        "cancellation_rate": 0.25,
        "execution_success_rate": 0.5,
    }


def test_model_success_rate_excludes_unknown_calls_from_denominator():
    """模型成功率遵循已知终态口径，UNKNOWN 调用由明细单独披露。"""
    assert _model_success_rate(3, 1) == 0.75
    assert _model_success_rate(0, 0) is None


def test_runtime_overview_reports_measured_model_latency_percentiles(api, admin, db):
    """模型 P50/P95 排除零时长占位，并对明细暴露样本数与已知成功率。"""
    project = api.post("/projects", username=admin, json={"name": unique("runtime-metrics")})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    user = db.query(User).filter_by(username=admin).one()
    task = Task(project_id=project_id, created_by=user.id, title="指标样本", goal="只用于测试")
    db.add(task)
    db.flush()
    now = datetime.now()
    run = TaskRun(
        task_id=task.id, run_number=1, goal_snapshot="只用于测试", status="SUCCEEDED",
        started_at=now - timedelta(minutes=1), finished_at=now,
    )
    db.add(run)
    db.flush()
    run.execution_root_run_id = run.id
    work = TaskWorkItem(
        task_run_id=run.id, work_key="metrics", kind="PLAN", status="SUCCEEDED",
        idempotency_key=unique("metrics"),
    )
    db.add(work)
    db.flush()
    attempt = TaskAttempt(
        work_item_id=work.id, attempt_number=1, lease_generation=1, owner="metrics-test",
        status="SUCCEEDED", started_at=now - timedelta(minutes=1),
        heartbeat_at=now, finished_at=now,
    )
    db.add(attempt)
    db.flush()
    for status, duration_ms in zip(
        ("SUCCEEDED", "SUCCEEDED", "FAILED", "SUCCEEDED", "UNKNOWN", "UNKNOWN"),
        (10, 20, 30, 40, 50, 0), strict=True,
    ):
        db.add(RuntimeCallFact(
            call_id=f"metrics-{uuid4().hex}", project_id=project_id, task_id=task.id,
            task_run_id=run.id, execution_root_run_id=run.id, work_item_id=work.id,
            attempt_id=attempt.id, model_name="metrics-model", model_revision="v1",
            status=status, duration_ms=duration_ms, finished_at=now, created_at=now,
        ))
    db.commit()

    overview = runtime_overview(
        db, project_id=project_id,
        from_at=now - timedelta(minutes=5), to_at=now + timedelta(seconds=1),
    )

    row = overview["models"][0]
    assert overview["summary"]["model_calls"] == 6
    assert overview["summary"]["model_success_rate"] == 0.75
    assert overview["summary"]["model_latency_sample_count"] == 5
    assert overview["summary"]["p50_model_latency_ms"] == 30
    assert overview["summary"]["p95_model_latency_ms"] == 48
    assert row["known_calls"] == 4
    assert row["unknown_calls"] == 2
    assert row["success_rate"] == 0.75
    assert row["latency_sample_count"] == 5
    assert row["avg_latency_ms"] == 30
    unknown_provider = next(item for item in overview["providers"] if item["provider"] == "UNKNOWN")
    assert unknown_provider["calls"] == 6
    assert unknown_provider["known_calls"] == 4
    assert unknown_provider["status"] == "INSUFFICIENT_SAMPLE"
    assert unknown_provider["success_rate"] == 0.75


def test_task_metrics_query_filters_roots_and_buckets_terminal_by_finish_time():
    """执行根避免 Fan-out 重复；终态和未完成状态按不同时间字段入窗。"""
    end = datetime(2026, 11, 11)
    statement = select(TaskRun.id).where(
        _execution_root_filter(), _task_run_window_filter(end - timedelta(days=7), end),
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "task_run.execution_root_run_id = task_run.id" in sql
    assert "task_run.finished_at" in sql
    assert "task_run.created_at" in sql
    assert "task_run.status NOT IN" in sql


def test_unbound_model_stays_admitted_and_disabled_revision_does_not():
    """没有模型中心绑定时沿用旧配置；绑定修订停用后不再准入。"""

    class MissingBinding:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return None

    class OpenDB:
        def query(self, _model):
            return MissingBinding()

    assert model_revision_admitted(OpenDB(), 1) is True

    class Bound:
        def filter(self, *_args, **_kwargs):
            return self

        def first(self):
            return SimpleNamespace(revision_id=9)

    class ClosedDB:
        def query(self, _model):
            return Bound()

        def get(self, _model, _ident):
            return SimpleNamespace(enabled=False)

    assert model_revision_admitted(ClosedDB(), 1) is False


def test_project_token_quota_blocks_when_recorded_usage_reaches_limit(api, admin, db, monkeypatch):
    """额度只统计已落库 Token，达到上限后拒绝新的模型调用。"""
    monkeypatch.setattr(settings, "AGENT_PROJECT_DAILY_TOKEN_QUOTA", 10)
    monkeypatch.setattr(settings, "AGENT_USER_DAILY_TOKEN_QUOTA", 0)
    project = api.post("/projects", username=admin, json={"name": unique("quota")})
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    user = db.query(User).filter_by(username=admin).one()
    now = datetime.now()
    task = Task(project_id=project_id, created_by=user.id, title="额度样本", goal="只用于测试")
    db.add(task)
    db.flush()
    run = TaskRun(task_id=task.id, run_number=1, goal_snapshot="只用于测试", status="SUCCEEDED")
    db.add(run)
    db.flush()
    run.execution_root_run_id = run.id
    work = TaskWorkItem(
        task_run_id=run.id, work_key="quota", kind="PLAN", status="SUCCEEDED",
        idempotency_key=unique("quota"),
    )
    db.add(work)
    db.flush()
    attempt = TaskAttempt(
        work_item_id=work.id, attempt_number=1, lease_generation=1, owner="quota-test",
        status="SUCCEEDED", started_at=now, heartbeat_at=now, finished_at=now,
    )
    db.add(attempt)
    db.flush()
    db.add(RuntimeCallFact(
        call_id=f"quota-{uuid4().hex}", project_id=project_id, task_id=task.id,
        task_run_id=run.id, execution_root_run_id=run.id, work_item_id=work.id,
        attempt_id=attempt.id, model_name="quota-model", status="SUCCEEDED",
        total_tokens=10, usage_status="KNOWN", duration_ms=1, created_at=now, finished_at=now,
    ))
    db.commit()

    with pytest.raises(LLMError) as error:
        assert_token_quota(db, project_id=project_id, user_id=user.id)
    assert error.value.code == "TOKEN_QUOTA_EXCEEDED"
    assert error.value.retryable is False


def test_failed_child_run_downgrades_root_success(api, admin, db):
    """协调根不能在子运行已失败时保持完全成功。"""
    project = api.post("/projects", username=admin, json={"name": unique("root-status")})
    assert project.status_code == 201, project.text
    user = db.query(User).filter_by(username=admin).one()
    task = Task(project_id=project.json()["id"], created_by=user.id, title="状态", goal="只用于测试", status="RUNNING")
    db.add(task)
    db.flush()
    root = TaskRun(
        task_id=task.id, run_number=1, goal_snapshot="只用于测试", status="SUCCEEDED", stage="COMPLETED",
    )
    db.add(root)
    db.flush()
    root.execution_root_run_id = root.id
    child = TaskRun(
        task_id=task.id, run_number=2, goal_snapshot="只用于测试", status="FAILED",
        execution_root_run_id=root.id,
    )
    db.add(child)
    db.commit()

    sync_task_status(db, task, root)

    assert root.status == "SUCCEEDED_WITH_ISSUES"
    assert root.stage == "COMPLETED_WITH_ISSUES"
    assert task.status == "SUCCEEDED_WITH_ISSUES"


def test_disabled_model_revision_is_not_loaded(db, monkeypatch):
    """停用修订后，所有模型加载入口都不再返回该配置。"""
    row = ModelConfiguration(
        domain_id=unique("blocked-model"), label="停用修订", provider="openai-compatible",
        api_base="http://model.invalid/v1", model_name="blocked", is_enabled=True,
    )
    db.add(row)
    db.commit()
    monkeypatch.setattr(
        "app.orchestration.tasks.services.runtime_fact_service.model_revision_admitted",
        lambda _db, _model_id: False,
    )
    from app.platform.model_configuration.services.model_config_service import load_model_for_provider

    assert load_model_for_provider(db, row.id) is None
