"""任务模块拆分的无数据库行为回归。"""

from types import SimpleNamespace

import pytest

from app.orchestration.tasks.runtime.handlers.reviewing import reconcile_review_facts
from app.orchestration.tasks.schemas import TaskReviewOutput


def _review_facts(*, report_total: int = 2) -> tuple[SimpleNamespace, SimpleNamespace]:
    """构造与正式 TestRun/报告字段一致的最小事实对象。"""
    test_run = SimpleNamespace(total=2, passed=1, failed=0, skipped=1, error=0)
    report = SimpleNamespace(
        status="COMPLETED", total_cases=report_total, passed_cases=1,
        failed_cases=0, skipped_cases=1, error_cases=0,
    )
    return test_run, report


def test_review_facts_allow_model_approval_when_official_facts_match():
    """模型批准只有在报告计数和已批准范围一致时才生效。"""
    test_run, report = _review_facts()
    approved, findings = reconcile_review_facts(
        TaskReviewOutput(approved=True, findings=[]), test_run, report, [10, 11],
    )

    assert approved is True
    assert findings == []


@pytest.mark.parametrize(
    ("report_total", "approved_case_ids", "security_status", "expected_finding"),
    [
        (2, [10, 11, 12], None, "执行覆盖 2/3 个已批准用例"),
        (1, [10, 11], None, "正式报告未完成或其计数与 TestRun 不一致"),
        (2, [10, 11], "MISSING", "安全评估未完成：MISSING"),
    ],
)
def test_review_facts_override_model_approval_for_incomplete_or_mismatched_evidence(
    report_total: int, approved_case_ids: list[int], security_status: str | None,
    expected_finding: str,
):
    """模型返回 approved=true 时，覆盖不足、统计不一致或安全事实缺失仍必须拒绝。"""
    test_run, report = _review_facts(report_total=report_total)
    approved, findings = reconcile_review_facts(
        TaskReviewOutput(approved=True, findings=[]), test_run, report, approved_case_ids,
        security_status=security_status,
    )

    assert approved is False
    assert expected_finding in findings
