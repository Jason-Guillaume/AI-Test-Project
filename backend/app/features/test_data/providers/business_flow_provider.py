"""BUSINESS_FLOW Provider（§9.3）：执行整条业务流程。

直接调 `execute_flow`。注意它会自己 **commit**——所以调用前先把本层已经写下的
`data_execution` 等行 flush 出去，调用后不要假设外层事务还包着这些记录。

按 §9.3 的「少改 execute_flow」路线：不新增 `context_out` 参数，只读
`FlowExecution.context_json` 里已经脱敏的 variables。代价是 **token 类输出无法从
流程结果回读**（脱敏会丢掉原值）。验收场景一的 `task_id` 不是敏感键，不受影响；
需要 token 的配方请改用 API_CREATE（它从内存结果取值）。
"""

from __future__ import annotations

from app.features.business.executors.business_flow_executor import execute_flow
from app.features.business.models.business_flow import BusinessFlow
from app.features.test_data.providers.base import BaseProvider, ProviderContext, ProviderResult, config_of
from app.shared.errors import CODE_DATA_RESOLVE_FAILED, CODE_PROVIDER_NOT_FOUND, AppError


class BusinessFlowProvider(BaseProvider):
    provider_type = "BUSINESS_FLOW"

    def run(self, ctx: ProviderContext) -> ProviderResult:
        """运行对应数据。"""
        from app.features.test_data.schemas import BusinessFlowProviderConfig

        cfg = self.load_config(config_of(ctx), BusinessFlowProviderConfig)

        flow = db_get_flow(ctx.db, cfg.business_flow_id)
        if flow is None or flow.project_id != ctx.project_id:
            raise AppError(
                f"业务流程 {cfg.business_flow_id} 不存在",
                status_code=404,
                code=CODE_PROVIDER_NOT_FOUND,
            )

        # environment_id 写死在配置里时必须与本次运行环境一致。
        if cfg.environment_id is not None and cfg.environment_id != ctx.environment.id:
            raise AppError(
                f"Provider 配置的 environment_id={cfg.environment_id} 与本次运行环境 "
                f"{ctx.environment.id} 不一致",
                status_code=400,
                code=CODE_DATA_RESOLVE_FAILED,
            )

        # execute_flow 内部会 commit：先把本层未落库的记录 flush 出去。
        ctx.db.flush()

        variables = dict(ctx.variables or {})
        variables.update(dict(cfg.input_variables or {}))

        execution = execute_flow(
            ctx.db,
            cfg.business_flow_id,
            environment_id=ctx.environment.id,
            variables=variables,
            actor=ctx.actor,
        )

        context_json = execution.context_json or {}
        masked_vars = context_json.get("variables") if isinstance(context_json, dict) else None
        outputs = dict(masked_vars or {})
        outputs["flow_execution_id"] = execution.id

        if execution.status != "SUCCESS":
            return ProviderResult.fail(
                execution.error_code or "BUSINESS_FLOW_FAILED",
                execution.error_message or "业务流程执行失败",
                outputs=outputs,
            )
        return ProviderResult.ok(
            outputs,
            request_snapshot={"flow_id": cfg.business_flow_id, "flow_execution_id": execution.id},
            response_snapshot={"status": execution.status},
        )


def db_get_flow(db, flow_id: int) -> BusinessFlow | None:
    """获取`db`流程。"""
    return db.get(BusinessFlow, flow_id)


__all__ = ["BusinessFlowProvider"]
