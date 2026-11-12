"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseExecutionResult:
    """单用例执行结果（由 run_service 落库为 CaseExecution）。"""

    status: str = "PENDING"  # 执行状态：PASSED/FAILED/ERROR/SKIPPED
    executor_type: str | None = None
    request_snapshot: dict[str, Any] | None = None
    response_snapshot: dict[str, Any] | None = None
    assertion_results: list[dict[str, Any]] = field(default_factory=list)
    context_json: dict[str, Any] | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
