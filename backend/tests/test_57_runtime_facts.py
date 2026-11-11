"""运行事实白名单元数据测试。"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.orchestration.tasks.models import TaskRun
from app.orchestration.tasks.services.runtime_fact_service import (
    _execution_root_filter, _safe_metadata, _skill_identity,
    _task_run_status_metrics, _task_run_window_filter,
)


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
