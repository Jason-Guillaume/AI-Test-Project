"""security_testing 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from app.features.security_testing.schemas.common import BaselineStatus
from app.features.security_testing.schemas.common import _ORM


class SecurityRunRequest(BaseModel):
    """安全用例批量执行：内部走既有 TestPlan + TestRun，不写第二套执行器。"""

    security_case_ids: list[int] = Field(..., min_length=1, max_length=200)
    environment_id: int | None = None
    plan_name: str | None = Field(None, max_length=200)


class SecurityExecutionRead(_ORM):
    """一次安全执行记录。mutation_trace 与 evidence 都已脱敏。"""

    id: int
    project_id: int
    test_run_id: int | None = None
    case_execution_id: int | None = None
    security_case_id: int
    environment_id: int | None = None
    actor_id: int | None = None
    baseline_status: BaselineStatus | None = None
    baseline_http_status: int | None = None
    security_result: str
    classification: str | None = None
    mutation_trace: list[dict[str, Any]] = Field(default_factory=list)
    replay_count: int = 1
    actual_status_codes: list[int] = Field(default_factory=list)
    evidence: dict[str, Any] | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime | None = None
