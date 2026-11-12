"""security_execution 读取。

执行本身没有独立服务——安全用例由 ``test_case_executor`` 的分支调用
``runner.run_security_case``，写库发生在执行链路里。这里只补查询侧：
从 ``GET /test-runs/{run_id}/cases`` 拿到的 ``context_json.security_execution_id``
再查这一次安全执行的结论、脱敏 trace 与证据。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.security_testing.models import SecurityExecution
from app.features.security_testing.schemas import SecurityExecutionRead
from app.platform.projects.services.access_service import get_project_or_404
from app.core.models.identity import User
from app.core.http.errors import CODE_SECURITY_EXECUTION_FAILED, AppError

__all__ = ["ExecutionQueryService"]


class ExecutionQueryService:
    """只读。不可见项目与不存在共用 404（隐藏存在性）。"""

    @staticmethod
    def get_execution(
        db: Session, security_execution_id: int, *, user: User
    ) -> SecurityExecutionRead:
        """获取执行记录。"""
        row = db.get(SecurityExecution, security_execution_id)
        if row is None:
            raise AppError(
                "安全执行记录不存在",
                status_code=404,
                code=CODE_SECURITY_EXECUTION_FAILED,
            )
        get_project_or_404(db, row.project_id, user)
        return SecurityExecutionRead.model_validate(row)
