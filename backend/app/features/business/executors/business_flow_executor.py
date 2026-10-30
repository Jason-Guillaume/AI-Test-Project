"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.business.executors.contracts import ActionRunResult
from app.features.business.executors.action_executor import run_action

from datetime import datetime
from sqlalchemy.orm import Session
from app.features.business.executors.context import ExecutionContext
from app.platform.environment_configuration.services.environment_service import resolve_project_environment
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.execution import FlowExecution
from app.core.models.identity import User
from app.core.http.errors import not_found
from app.features.business.models.business_flow import BusinessFlow as _FlowModel
from app.features.business.executors.result_writer import execute_action
from app.features.business.executors.masking import mask_context_for_storage


def execute_flow(
    db: Session,
    flow_id: int,
    *,
    environment_id: int,
    variables: dict[str, object] | None = None,
    actor: User,
) -> FlowExecution:
    """执行一个业务流程。

    Args:
        db: 数据库会话。
        flow_id: 业务流程ID。
        environment_id: 执行环境ID。
        variables: 初始运行时变量。
        actor: 执行用户。

    Returns:
        FlowExecution: 执行记录（状态已更新）。
    """
    # 1. 加载环境与流程。
    # 资源不存在统一返 404（AppError 体系）：裸 ValueError 会被全局 handler
    # 归为 500「服务器内部错误」，用户看不到可读提示。
    flow = db.get(_FlowModel, flow_id)
    if flow is None:
        raise not_found("业务流程不存在")
    environment = resolve_project_environment(db, flow.project_id, environment_id)

    # 2. 创建执行记录。
    execution = FlowExecution(
        project_id=flow.project_id,
        flow_id=flow_id,
        environment_id=environment_id,
        status="RUNNING",
        started_at=datetime.now(),
        context_json=variables or {},
        created_by=actor.id,
    )
    db.add(execution)
    db.flush()

    ctx = ExecutionContext(variables=variables or {})

    # 3. 加载按 sort 排序的动作列表。
    actions = (
        db.query(BusinessAction)
        .filter(BusinessAction.flow_id == flow_id)
        .order_by(BusinessAction.sort.asc(), BusinessAction.id.asc())
        .all()
    )

    # 4. 顺序执行每个动作。
    # seq 从 0 开始，直接作为 ActionExecution.sequence：该列
    # server_default 为 0，注释为「执行序号（从 0 开始）」，故无需 +1。
    for seq, action in enumerate(actions):
        action_exec = execute_action(
            db, execution, action, environment, ctx, project_id=flow.project_id,
            sequence=seq,
        )
        if action_exec.status == "FAILED":
            execution.status = "FAILED"
            execution.error_code = action_exec.error_code
            execution.error_message = action_exec.error_message
            execution.finished_at = datetime.now()
            # 保存当前上下文（脱敏后）。
            execution.context_json = mask_context_for_storage(ctx)
            db.commit()
            return execution

    # 5. 所有步骤成功。
    execution.status = "SUCCESS"
    execution.context_json = mask_context_for_storage(ctx)
    execution.finished_at = datetime.now()
    db.commit()
    return execution


__all__ = [
    'ActionRunResult',
    'run_action',
]
