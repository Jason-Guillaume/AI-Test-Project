"""STATIC Provider（§9.5）：字面量原样写入私有变量，没有网络、没有数据库。

字符串值里的 ``${...}`` 先经 VariableResolver 求值——这样 STATIC 步骤可以引用
前置步骤的输出（例如 ``{"project_id": "${fixture.ACTIVE_PROJECT.project_id}"}``），
不用为这种小场景再引一个 API 步骤。
"""

from __future__ import annotations

from app.features.test_data.providers.base import (
    BaseProvider,
    ProviderContext,
    ProviderResult,
    config_of,
)
from app.features.test_data.runtime.variable_resolver import resolve_template
from app.shared.errors import CODE_VARIABLE_RESOLVE_FAILED, AppError


class StaticProvider(BaseProvider):
    provider_type = "STATIC"

    def run(self, ctx: ProviderContext) -> ProviderResult:
        from app.features.test_data.schemas import StaticProviderConfig

        cfg = self.load_config(config_of(ctx), StaticProviderConfig)

        try:
            outputs = resolve_template(dict(cfg.values or {}), ctx.scope, required=True)
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise AppError(
                f"STATIC 配置求值失败：{exc}",
                status_code=400,
                code=CODE_VARIABLE_RESOLVE_FAILED,
            ) from exc

        return ProviderResult.ok(outputs)


__all__ = ["StaticProvider"]
