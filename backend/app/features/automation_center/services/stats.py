"""自动化执行统计。

通过率分母是实际执行的用例，跳过用例不计入，也不单独构成失败。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

TERMINAL_STATUSES = {"SUCCESS", "FAILED", "CANCELLED", "TIMEOUT"}
_PIPELINE_STATUS = {
    "SUCCESS": "SUCCESS",
    "PASS": "SUCCESS",
    "PASSED": "SUCCESS",
    "FAIL": "FAILED",
    "FAILED": "FAILED",
    "FAILURE": "FAILED",
    "RUNNING": "RUNNING",
    "PENDING": "PENDING",
    "WAITING": "PENDING",
    "QUEUED": "PENDING",
    "CANCEL": "CANCELLED",
    "CANCELED": "CANCELLED",
    "CANCELLED": "CANCELLED",
    "TIMEOUT": "TIMEOUT",
    "TIMED_OUT": "TIMEOUT",
}


def pass_rate(*, passed: int, failed: int, broken: int, skipped: int, unknown: int) -> Decimal:
    """计算通过率。跳过用例不进入分母；全部跳过且没有失败时记为 100。"""
    executed = passed + failed + broken + unknown
    if executed <= 0:
        return Decimal("100.00") if skipped > 0 else Decimal("0.00")
    rate = (Decimal(passed) / Decimal(executed)) * Decimal(100)
    return rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def map_pipeline_status(payload: dict | str | None) -> str:
    """把云效运行状态归一成平台状态。缺少总状态时根据任务状态归纳。"""
    if isinstance(payload, str):
        return _PIPELINE_STATUS.get(payload.upper(), "RUNNING")
    if not isinstance(payload, dict):
        return "RUNNING"
    raw = str(payload.get("status") or "").upper()
    if raw:
        return _PIPELINE_STATUS.get(raw, "RUNNING")
    job_statuses: list[str] = []
    for stage in payload.get("stages") or []:
        info = stage.get("stageInfo") if isinstance(stage, dict) else None
        jobs = (info or stage or {}).get("jobs") if isinstance(info or stage, dict) else []
        for job in jobs or []:
            if isinstance(job, dict):
                job_statuses.append(str(job.get("status") or "").upper())
    if not job_statuses:
        return "RUNNING"
    mapped = [_PIPELINE_STATUS.get(item, "RUNNING") for item in job_statuses]
    if "FAILED" in mapped or "TIMEOUT" in mapped:
        return "FAILED" if "FAILED" in mapped else "TIMEOUT"
    if "CANCELLED" in mapped:
        return "CANCELLED"
    if all(item == "SUCCESS" for item in mapped):
        return "SUCCESS"
    return "RUNNING"


def apply_test_outcome(pipeline_status: str, *, failed: int, broken: int) -> str:
    """流水线成功但存在失败或中断用例时，执行结果记为失败。仅跳过保持成功。"""
    if pipeline_status in {"CANCELLED", "TIMEOUT", "FAILED"}:
        return pipeline_status
    if pipeline_status == "SUCCESS" and (failed > 0 or broken > 0):
        return "FAILED"
    return pipeline_status
