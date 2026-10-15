"""业务流程执行服务层。

负责执行请求的校验、执行记录查询，以及调用底层 BusinessFlowExecutor。
service owns commit；router 不提交。

端点：
- execute_flow(db, flow_id, body, actor) → FlowExecutionResponse
- get_execution(db, execution_id, user) → FlowExecutionResponse
- list_execution_actions(db, execution_id, user) → FlowExecutionActionListResponse
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.business.executors.business_flow_executor import execute_flow as _executor_execute
from app.features.business.models.business_flow import BusinessFlow
from app.features.business.models.execution import ActionExecution, FlowExecution
from app.features.business.schemas import (
    ActionExecutionResponse,
    FlowExecutionActionListResponse,
    FlowExecutionRequest,
    FlowExecutionResponse,
)
from app.features.business.services._access import get_project_or_404
from app.models.identity import User
from app.shared.errors import not_found


def _execution_response(execution: FlowExecution) -> FlowExecutionResponse:
    return FlowExecutionResponse.model_validate(execution)


class ExecutionService:
    """业务流程执行服务。无状态，路由层复用单例。"""

    def execute_flow(
        self, db: Session, flow_id: int, body: FlowExecutionRequest, *, actor: User
    ) -> FlowExecutionResponse:
        """执行业务流程。"""
        flow = db.get(BusinessFlow, flow_id)
        if flow is None:
            raise not_found("业务流程不存在")
        get_project_or_404(db, flow.project_id, actor)

        # 调用底层执行器（内部完成 commit）。
        execution = _executor_execute(
            db, flow_id,
            environment_id=body.environment_id,
            variables=body.variables,
            actor=actor,
        )
        return _execution_response(execution)

    def get_execution(
        self, db: Session, execution_id: int, user: User
    ) -> FlowExecutionResponse:
        """查询执行记录详情。"""
        execution = db.get(FlowExecution, execution_id)
        if execution is None:
            raise not_found("执行记录不存在")
        get_project_or_404(db, execution.project_id, user)
        return _execution_response(execution)

    def list_execution_actions(
        self, db: Session, execution_id: int, user: User
    ) -> FlowExecutionActionListResponse:
        """查询执行记录中的步骤执行列表。"""
        execution = db.get(FlowExecution, execution_id)
        if execution is None:
            raise not_found("执行记录不存在")
        get_project_or_404(db, execution.project_id, user)

        items = (
            db.query(ActionExecution)
            .filter(ActionExecution.flow_execution_id == execution_id)
            .order_by(ActionExecution.sequence.asc(), ActionExecution.id.asc())
            .all()
        )
        responses = [ActionExecutionResponse.model_validate(a) for a in items]
        return FlowExecutionActionListResponse(
            items=responses,
            total=len(responses),
            page=1,
            page_size=100,
        )
