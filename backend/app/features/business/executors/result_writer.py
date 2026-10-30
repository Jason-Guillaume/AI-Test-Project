"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from datetime import datetime
from sqlalchemy.orm import Session
from app.features.business.executors.context import ExecutionContext
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.execution import ActionExecution, FlowExecution
from app.core.models.configuration import Environment
from app.features.business.executors.masking import mask_web_secrets
from app.features.business.executors.action_executor import run_action_core


def execute_action(
    db: Session,
    execution: FlowExecution,
    action: BusinessAction,
    environment: Environment,
    ctx: ExecutionContext,
    *,
    project_id: int,
    sequence: int = 0,
) -> ActionExecution:
    """执行单个业务动作并落库 ActionExecution。

    只负责「建行 + 把核心结果搬进字段」；前置条件、绑定、映射、HTTP、输出回写都在
    ``run_action_core`` 里，与 ``run_action`` 共用，避免两套绑定查询漂移。
    """
    action_exec = ActionExecution(
        flow_execution_id=execution.id,
        action_id=action.id,
        sequence=sequence,
        status="RUNNING",
        started_at=datetime.now(),
    )
    db.add(action_exec)
    db.flush()

    result = run_action_core(
        db, action, environment=environment, ctx=ctx,
        project_id=project_id, flow_id=execution.flow_id,
    )
    action_exec.status = result.status
    action_exec.error_code = result.error_code
    action_exec.error_message = result.error_message
    action_exec.duration_ms = result.duration_ms
    action_exec.binding_id = result.binding_id
    # 原实现把列表原样赋上去（可能为空列表）：保持空列表而不是 NULL，
    # 避免 report / 前端把它当「未采集」而不是「采集到 0 条」。
    action_exec.unverified_preconditions = result.unverified_preconditions
    action_exec.input_context = mask_web_secrets(result.input_context, ctx)
    action_exec.output_context = mask_web_secrets(result.output_context, ctx)
    action_exec.request_snapshot = mask_web_secrets(result.request_snapshot, ctx)
    action_exec.response_snapshot = mask_web_secrets(result.response_snapshot, ctx)
    action_exec.finished_at = datetime.now()
    return action_exec
