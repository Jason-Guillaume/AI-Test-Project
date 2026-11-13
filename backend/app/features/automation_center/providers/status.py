"""共享的外部运行状态映射。"""

from __future__ import annotations

_STATUS_MAP = {
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


def map_external_status(payload: dict | str | None) -> str:
    """把常见 CI 状态归一化；未知状态保持运行中，避免提前结束。"""
    if isinstance(payload, str):
        return _STATUS_MAP.get(payload.upper(), "RUNNING")
    if not isinstance(payload, dict):
        return "RUNNING"
    raw = str(payload.get("status") or "").upper()
    if raw:
        return _STATUS_MAP.get(raw, "RUNNING")
    job_statuses: list[str] = []
    for stage in payload.get("stages") or []:
        info = stage.get("stageInfo") if isinstance(stage, dict) else None
        jobs = (info or stage or {}).get("jobs") if isinstance(info or stage, dict) else []
        for job in jobs or []:
            if isinstance(job, dict):
                job_statuses.append(str(job.get("status") or "").upper())
    if not job_statuses:
        return "RUNNING"
    mapped = [_STATUS_MAP.get(item, "RUNNING") for item in job_statuses]
    if "FAILED" in mapped or "TIMEOUT" in mapped:
        return "FAILED" if "FAILED" in mapped else "TIMEOUT"
    if "CANCELLED" in mapped:
        return "CANCELLED"
    if all(item == "SUCCESS" for item in mapped):
        return "SUCCESS"
    return "RUNNING"
