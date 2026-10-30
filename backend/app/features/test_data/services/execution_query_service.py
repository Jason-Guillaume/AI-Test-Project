"""造数执行记录查询服务（Phase A 只读；写入由 Phase B 运行时负责）。

列表与详情都走同一套脱敏出口：input_snapshot / output_snapshot / output_json
在写库时已经脱敏，这里再兜底一次，避免历史脏数据泄露。
"""

from __future__ import annotations

from sqlalchemy import func as sa_func, or_
from sqlalchemy.orm import Session

from app.core.security.sensitive import SensitiveDataMasker
from app.features.test_data.models.execution import (
    DataExecution,
    FixtureExecution,
    ProviderExecution,
)
from app.features.test_data.schemas import (
    DATA_EXECUTION_STATUSES,
    FixtureExecutionResponse,
    ProviderExecutionResponse,
    DataExecutionDetailResponse,
    DataExecutionListResponse,
    DataExecutionResponse,
)
from app.features.test_data.services.access_service import resolve_execution_project_id
from app.platform.projects.services.access_service import get_project_or_404
from app.core.models.identity import User
from app.core.http.errors import bad_request, not_found
from app.core.http.pagination import DEFAULT_PAGE_SIZE


def _mask(value: object) -> object:
    """脱敏对应数据。"""
    return SensitiveDataMasker.mask_body(value)


def _provider_response(row: ProviderExecution) -> ProviderExecutionResponse:
    """构造数据提供器响应数据。"""
    resp = ProviderExecutionResponse.model_validate(row)
    resp.input_snapshot = _mask(resp.input_snapshot)
    resp.output_snapshot = _mask(resp.output_snapshot)
    return resp


def _fixture_response(db: Session, row: FixtureExecution) -> FixtureExecutionResponse:
    """构造固定数据响应数据。"""
    resp = FixtureExecutionResponse.model_validate(row)
    resp.input_snapshot = _mask(resp.input_snapshot)
    resp.output_snapshot = _mask(resp.output_snapshot)
    providers = (
        db.query(ProviderExecution)
        .filter(ProviderExecution.fixture_execution_id == row.id)
        .order_by(ProviderExecution.started_at, ProviderExecution.id)
        .all()
    )
    resp.provider_executions = [_provider_response(p) for p in providers]
    return resp


def _response(db: Session, row: DataExecution) -> DataExecutionResponse:
    """列表项：附加 Fixture 数与 Provider 步数。"""
    resp = DataExecutionResponse.model_validate(row)
    fixture_rows = (
        db.query(FixtureExecution.id, FixtureExecution.fixture_key)
        .filter(FixtureExecution.data_execution_id == row.id)
        .all()
    )
    fixture_ids = [fr[0] for fr in fixture_rows]
    resp.fixture_key_count = len({fr[1] for fr in fixture_rows})
    filters = [ProviderExecution.data_execution_id == row.id]
    if fixture_ids:
        filters.append(ProviderExecution.fixture_execution_id.in_(fixture_ids))
    resp.provider_step_count = int(
        db.query(sa_func.count(ProviderExecution.id)).filter(or_(*filters)).scalar() or 0
    )
    return resp


class ExecutionQueryService:
    """执行记录只读服务。无状态，路由层复用单例。"""

    def list_executions(
        self, db: Session, project_id: int, user: User, *,
        status: str | None = None, test_run_id: int | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> DataExecutionListResponse:
        """列出`executions`。"""
        get_project_or_404(db, project_id, user)
        q = db.query(DataExecution).filter(DataExecution.project_id == project_id)
        if status:
            if status not in DATA_EXECUTION_STATUSES:
                raise bad_request(f"状态取值非法：{'/'.join(DATA_EXECUTION_STATUSES)}")
            q = q.filter(DataExecution.status == status)
        if test_run_id is not None:
            q = q.filter(DataExecution.test_run_id == test_run_id)
        total = int(q.count())
        items = (
            q.order_by(DataExecution.created_at.desc(), DataExecution.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return DataExecutionListResponse(
            items=[_response(db, r) for r in items], total=total, page=page, page_size=page_size
        )

    def get_execution(self, db: Session, data_execution_id: int, user: User) -> DataExecutionDetailResponse:
        """获取执行记录。"""
        row = db.get(DataExecution, data_execution_id)
        if row is None:
            raise not_found("造数执行记录不存在")
        get_project_or_404(db, resolve_execution_project_id(db, data_execution_id), user)
        detail = DataExecutionDetailResponse(**_response(db, row).model_dump())
        fixtures = (
            db.query(FixtureExecution)
            .filter(FixtureExecution.data_execution_id == row.id)
            .order_by(FixtureExecution.started_at, FixtureExecution.id)
            .all()
        )
        detail.fixture_executions = [_fixture_response(db, f) for f in fixtures]
        # 手工试跑单个 Provider 的记录没有 fixture_execution_id，只能挂在这一层。
        detail.provider_executions = [
            _provider_response(p)
            for p in (
                db.query(ProviderExecution)
                .filter(
                    ProviderExecution.data_execution_id == row.id,
                    ProviderExecution.fixture_execution_id.is_(None),
                )
                .order_by(ProviderExecution.started_at, ProviderExecution.id)
                .all()
            )
        ]
        return detail


__all__ = ["ExecutionQueryService"]
