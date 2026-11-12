"""同项目 TestRun 对比；只按持久化 test_case_id 对齐，不按名称或数组位置猜测。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.core.http.errors import bad_request, not_found
from app.core.models.identity import User
from app.features.test_management.models.execution import CaseExecution, TestRun
from app.features.test_management.models.test_case import TestCase
from app.features.test_management.schemas.executions import TestRunResponse
from app.features.test_management.services.access_service import get_project_or_404


FAILURE = {"FAILED", "ERROR"}
FINAL_CASE = {"PASSED", "FAILED", "ERROR", "SKIPPED"}


def compare_runs(
    db: Session, baseline_id: int, candidate_id: int, actor: User, *, page: int, page_size: int,
) -> dict[str, Any]:
    baseline = db.get(TestRun, baseline_id)
    candidate = db.get(TestRun, candidate_id)
    if baseline is None or candidate is None:
        raise not_found("测试运行不存在")
    get_project_or_404(db, baseline.project_id, actor)
    get_project_or_404(db, candidate.project_id, actor)
    if baseline.project_id != candidate.project_id:
        raise bad_request("只能比较同一项目内的测试运行")
    if baseline.id == candidate.id:
        raise bad_request("请选择两次不同的测试运行")
    if baseline.status not in {"SUCCESS", "FAILED", "CANCELLED"} or candidate.status not in {"SUCCESS", "FAILED", "CANCELLED"}:
        raise bad_request("测试运行仍在执行，完成后才能比较")

    baseline_rows = db.query(CaseExecution).filter(CaseExecution.test_run_id == baseline.id).order_by(CaseExecution.id.asc()).all()
    candidate_rows = db.query(CaseExecution).filter(CaseExecution.test_run_id == candidate.id).order_by(CaseExecution.id.asc()).all()
    baseline_types = {row.executor_type for row in baseline_rows if row.executor_type}
    candidate_types = {row.executor_type for row in candidate_rows if row.executor_type}
    if not baseline_types or baseline_types != candidate_types or len(baseline_types) != 1:
        raise bad_request("两次运行没有相同且唯一的执行类型，无法可靠比较")

    def group(rows: list[CaseExecution]):
        by_case: dict[int, list[CaseExecution]] = defaultdict(list)
        unaligned: list[CaseExecution] = []
        for row in rows:
            if row.test_case_id is None:
                unaligned.append(row)
            else:
                by_case[row.test_case_id].append(row)
        return by_case, unaligned

    before, before_unaligned = group(baseline_rows)
    after, after_unaligned = group(candidate_rows)
    case_ids = set(before) | set(after)
    case_names = dict(db.query(TestCase.id, TestCase.name).filter(TestCase.id.in_(case_ids)).all()) if case_ids else {}
    items: list[dict[str, Any]] = []
    counts = {key: 0 for key in ("new_failures", "restored", "persistent_failures", "passed", "added", "removed", "unresolved", "unalignable")}

    def failed(status: str | None) -> bool:
        return status in FAILURE

    for case_id in sorted(case_ids):
        before_rows, after_rows = before.get(case_id, []), after.get(case_id, [])
        if len(before_rows) > 1 or len(after_rows) > 1:
            counts["unalignable"] += 1
            items.append({"test_case_id": case_id, "case_name": case_names.get(case_id, f"用例 #{case_id}"), "state": "unalignable", "note": "同一运行中存在重复用例记录，不能确定稳定对应关系"})
            continue
        left = before_rows[0] if before_rows else None
        right = after_rows[0] if after_rows else None
        if left is None:
            state = "added"
            counts["added"] += 1
            note = "候选运行新增用例；没有基准结果可判断是否修复"
        elif right is None:
            state = "removed"
            counts["removed"] += 1
            note = "候选运行中没有此用例，不代表通过或已修复"
        elif left.status not in FINAL_CASE or right.status not in FINAL_CASE:
            state = "unresolved"
            counts["unresolved"] += 1
            note = "至少一侧未执行完成或被跳过，不能判定通过/修复"
        elif failed(left.status) and failed(right.status):
            state = "persistent_failure"
            counts["persistent_failures"] += 1
            note = None
        elif failed(left.status) and right.status == "PASSED":
            state = "restored"
            counts["restored"] += 1
            note = None
        elif left.status == "PASSED" and failed(right.status):
            state = "new_failure"
            counts["new_failures"] += 1
            note = None
        elif left.status == "PASSED" and right.status == "PASSED":
            state = "passed"
            counts["passed"] += 1
            note = None
        else:
            state = "unresolved"
            counts["unresolved"] += 1
            note = "状态组合不支持直接判定"
        items.append({
            "test_case_id": case_id,
            "case_name": case_names.get(case_id, f"用例 #{case_id}（资产已删除）"),
            "state": state,
            "baseline_execution_id": left.id if left else None,
            "baseline_status": left.status if left else None,
            "baseline_duration_ms": left.duration_ms if left else None,
            "candidate_execution_id": right.id if right else None,
            "candidate_status": right.status if right else None,
            "candidate_duration_ms": right.duration_ms if right else None,
            "duration_delta_ms": right.duration_ms - left.duration_ms if left and right and right.duration_ms is not None and left.duration_ms is not None else None,
            "note": note,
        })

    for side, rows in (("基准", before_unaligned), ("候选", after_unaligned)):
        for row in rows:
            counts["unalignable"] += 1
            items.append({
                "test_case_id": None,
                "case_name": f"{side}运行中已删除用例的执行 #{row.id}",
                "state": "unalignable",
                "baseline_execution_id": row.id if side == "基准" else None,
                "baseline_status": row.status if side == "基准" else None,
                "candidate_execution_id": row.id if side == "候选" else None,
                "candidate_status": row.status if side == "候选" else None,
                "note": "缺少稳定用例 ID，无法与另一侧对齐",
            })
    items.sort(key=lambda row: (row["test_case_id"] is None, row["test_case_id"] or 0, row["case_name"]))
    return {
        "project_id": baseline.project_id,
        "baseline": TestRunResponse.model_validate(baseline),
        "candidate": TestRunResponse.model_validate(candidate),
        "executor_types": sorted(baseline_types),
        "environment_changed": baseline.environment_id != candidate.environment_id,
        "counts": counts,
        "items": items[(page - 1) * page_size:page * page_size],
        "total": len(items),
        "page": page,
        "page_size": page_size,
    }
