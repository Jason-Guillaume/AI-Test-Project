"""MockContext 管理面查询（§二十六 执行作用域）。

只读列表 / 详情 + 手动关闭。Context 由 run_service 在用例执行时自动激活 / 关闭，
这里只提供「看与手动收尾」的入口，不负责激活（激活走 runtime 层）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.features.mocking.models import MockContext
from app.features.mocking.schemas import MockContextResponse
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.features.mocking.services.mock_runtime_service import (
    MockRuntimeService,
)
from app.core.models.identity import User
from app.core.http.errors import not_found
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


class MockContextService:
    """Mock 执行作用域管理。无状态，路由层复用单例。"""

    def __init__(self) -> None:
        """初始化对象状态。"""
        self._runtime = MockRuntimeService()

    def list_contexts(
        self, db: Session, project_id: int, user: User, *,
        status: str | None = None, test_run_id: int | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> list[MockContextResponse]:
        """列出`contexts`。"""
        get_project_or_404(db, project_id, user)
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        q = db.query(MockContext).filter(MockContext.project_id == project_id)
        if status:
            q = q.filter(MockContext.status == status.upper())
        if test_run_id is not None:
            q = q.filter(MockContext.test_run_id == test_run_id)
        total = int(q.count())
        items = (
            q.order_by(MockContext.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return [MockContextResponse.model_validate(c) for c in items]

    def get_context(self, db: Session, context_id: str, user: User) -> MockContextResponse:
        """获取上下文。"""
        ctx = (
            db.query(MockContext)
            .filter(MockContext.context_id == context_id)
            .first()
        )
        if ctx is None:
            raise not_found("Mock 执行作用域不存在")
        get_project_or_404(db, ctx.project_id, user)
        return MockContextResponse.model_validate(ctx)

    def close_context(self, db: Session, context_id: str, *, actor: User) -> MockContextResponse:
        """关闭上下文。"""
        ctx = (
            db.query(MockContext)
            .filter(MockContext.context_id == context_id)
            .first()
        )
        if ctx is None:
            raise not_found("Mock 执行作用域不存在")
        require_writable_project(db, ctx.project_id, actor)
        if ctx.status == "ACTIVE":
            ctx.status = "CLOSED"
            ctx.closed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(ctx)
        return MockContextResponse.model_validate(ctx)

    def expire_stale(self, db: Session, *, actor: User) -> int:
        """手动触发过期回收（平台管理员 / 项目可写均可调用）。"""
        return self._runtime.expire_stale_contexts(db)


__all__ = ["MockContextService"]
