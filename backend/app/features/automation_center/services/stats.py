"""自动化执行统计。

通过率分母是实际执行的用例，跳过用例不计入，也不单独构成失败。
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.features.automation_center.providers.status import map_external_status

TERMINAL_STATUSES = {"SUCCESS", "FAILED", "CANCELLED", "TIMEOUT"}


def pass_rate(*, passed: int, failed: int, broken: int, skipped: int, unknown: int) -> Decimal:
    """计算通过率。跳过用例不进入分母；全部跳过且没有失败时记为 100。"""
    executed = passed + failed + broken + unknown
    if executed <= 0:
        return Decimal("100.00") if skipped > 0 else Decimal("0.00")
    rate = (Decimal(passed) / Decimal(executed)) * Decimal(100)
    return rate.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def map_pipeline_status(payload: dict | str | None) -> str:
    """兼容旧调用名，把外部运行状态归一成平台状态。"""
    return map_external_status(payload)


def apply_test_outcome(pipeline_status: str, *, failed: int, broken: int) -> str:
    """流水线成功但存在失败或中断用例时，执行结果记为失败。仅跳过保持成功。"""
    if pipeline_status in {"CANCELLED", "TIMEOUT", "FAILED"}:
        return pipeline_status
    if pipeline_status == "SUCCESS" and (failed > 0 or broken > 0):
        return "FAILED"
    return pipeline_status
