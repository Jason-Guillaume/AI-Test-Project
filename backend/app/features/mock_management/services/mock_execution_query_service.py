"""MockExecution 查询服务（§十八 调用记录，只读）。

列表支持按 test_run_id / case_execution_id / service_id / matched / context 过页。
快照在写入时已脱敏（§五十），这里直接展示。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.mock_management.models import MockExecution
from app.features.mock_management.schemas import (
    MockExecutionListResponse,
    MockExecutionResponse,
)
from app.features.mock_management.services._access import (
    get_project_or_404,
    resolve_execution_project_id,
)
from app.features.mock_management.services._response import execution_response
from app.models.identity import User
from app.shared.errors import not_found
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class MockExecutionQueryService:
    """Mock 调用记录查询。无状态，路由层复用单例。"""

    def list_executions(
        self, db: Session, project_id: int, user: User, *,
        test_run_id: int | None = None,
        case_execution_id: int | None = None,
        service_id: int | None = None,
        matched: bool | None = None,
        context_id: str | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MockExecutionListResponse:
        get_project_or_404(db, project_id, user)
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        q = db.query(MockExecution).filter(MockExecution.project_id == project_id)
        if test_run_id is not None:
            q = q.filter(MockExecution.test_run_id == test_run_id)
        if case_execution_id is not None:
            q = q.filter(MockExecution.case_execution_id == case_execution_id)
        if service_id is not None:
            q = q.filter(MockExecution.mock_service_id == service_id)
        if matched is not None:
            q = q.filter(MockExecution.matched.is_(matched))
        if context_id:
            q = q.filter(MockExecution.mock_context_id == context_id)
        total = int(q.count())
        items = (
            q.order_by(MockExecution.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return MockExecutionListResponse(
            items=[execution_response(db, e) for e in items],
            total=total, page=page, page_size=page_size,
        )

    def get_execution(self, db: Session, execution_id: int, user: User) -> MockExecutionResponse:
        row = db.get(MockExecution, execution_id)
        if row is None:
            raise not_found("Mock 调用记录不存在")
        get_project_or_404(db, resolve_execution_project_id(db, execution_id), user)
        return execution_response(db, row)


__all__ = ["MockExecutionQueryService"]
