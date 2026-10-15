"""BUSINESS_ACTION Provider（§9.2）：执行**单个**业务动作，不跑整条流程。

调用 `business_flow_executor.run_action`，它复用业务执行器的前置条件、默认绑定、
映射解析、ApiRequestExecutor 与输出回写——Data Factory 不复制这些查询。

不要调用 `execute_flow` 来跑单个动作，否则整条流程都会被跑完，且它自己会 commit，
外层事务边界不可控。
"""

from __future__ import annotations

from app.features.business.executors.business_flow_executor import ActionRunResult, run_action
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_flow import BusinessFlow
from app.features.test_data.providers.base import BaseProvider, ProviderContext, ProviderResult, config_of
from app.shared.errors import CODE_PROVIDER_NOT_FOUND, AppError


class BusinessActionProvider(BaseProvider):
    provider_type = "BUSINESS_ACTION"

    def run(self, ctx: ProviderContext) -> ProviderResult:
        from app.features.test_data.schemas import BusinessActionProviderConfig

        cfg = self.load_config(config_of(ctx), BusinessActionProviderConfig)
        action = self._resolve_action(ctx, cfg)

        ctx.variables = dict(ctx.variables or {})
        result = run_action(
            ctx.db,
            action.id,
            environment=ctx.environment,
            variables=ctx.variables,
            actor=ctx.actor,
            project_id=ctx.project_id,
        )
        return _to_result(result)

    @staticmethod
    def _resolve_action(ctx: ProviderContext, cfg) -> BusinessAction:
        """按 business_action_id，或 flow_id + action_key 定位动作并校验归属。"""
        db = ctx.db
        if cfg.business_action_id is not None:
            action = db.get(BusinessAction, cfg.business_action_id)
        else:
            if cfg.flow_id is None or cfg.action_key is None:
                raise AppError(
                    "BUSINESS_ACTION 配置需要 business_action_id，或 flow_id + action_key",
                    status_code=400,
                    code=CODE_PROVIDER_NOT_FOUND,
                )
            action = db.query(BusinessAction).filter(
                BusinessAction.flow_id == cfg.flow_id,
                BusinessAction.action_key == cfg.action_key,
            ).first()
            flow = db.get(BusinessFlow, cfg.flow_id)
            if flow is not None and flow.project_id != ctx.project_id:
                raise AppError(
                    f"业务流程 {cfg.flow_id} 不存在",
                    status_code=404,
                    code=CODE_PROVIDER_NOT_FOUND,
                )
        if action is None:
            raise AppError(
                "业务动作不存在",
                status_code=404,
                code=CODE_PROVIDER_NOT_FOUND,
            )
        flow = db.get(BusinessFlow, action.flow_id)
        # 动作本身没有 project_id，归属经 flow 判定；跨项目隐藏为「不存在」。
        if flow is None or flow.project_id != ctx.project_id:
            raise AppError(
                "业务动作不存在",
                status_code=404,
                code=CODE_PROVIDER_NOT_FOUND,
            )
        return action


def _to_result(result: ActionRunResult) -> ProviderResult:
    """把动作执行结果转成 ProviderResult；动作输出合并回私有变量由 data_factory 做。"""
    if result.status == "SUCCESS":
        return ProviderResult.ok(
            result.outputs,
            request_snapshot=result.request_snapshot,
            response_snapshot=result.response_snapshot,
        )
    return ProviderResult.fail(
        result.error_code or "BUSINESS_ACTION_FAILED",
        result.error_message or "业务动作执行失败",
        request_snapshot=result.request_snapshot,
        response_snapshot=result.response_snapshot,
    )


__all__ = ["BusinessActionProvider"]
