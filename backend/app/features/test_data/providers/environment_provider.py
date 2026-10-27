"""ENVIRONMENT Provider（§9.5）：读取本次运行环境的某个键。

键名单（属性名 / default_headers 键）集中定义在
``variable_resolver.ENV_ATTR_KEYS`` 与 ``resolve_env_key``——ENVIRONMENT 步骤、
`${env.X}` 模板、以及用例执行器都走这同一份实现，避免三份名单漂移。
这里只做一个薄的转接，把键的读取出口收敛到这一个 Provider 模块。
"""

from __future__ import annotations

from app.features.test_data.providers.base import (
    BaseProvider,
    ProviderContext,
    ProviderResult,
    config_of,
)
from app.features.test_data.runtime.variable_resolver import resolve_env_key

__all__ = ["EnvironmentProvider", "resolve_env_key"]


class EnvironmentProvider(BaseProvider):
    provider_type = "ENVIRONMENT"

    def run(self, ctx: ProviderContext) -> ProviderResult:
        """运行对应数据。"""
        from app.features.test_data.schemas import EnvironmentProviderConfig

        cfg = self.load_config(config_of(ctx), EnvironmentProviderConfig)
        key = cfg.key.strip()
        value = resolve_env_key(ctx.environment, key)
        # 键不存在时 resolve_env_key 返回空串；这里明确报出来，避免静默注入 ""。
        if value == "":
            return ProviderResult.fail(
                "ENVIRONMENT_KEY_NOT_FOUND",
                f"环境 {ctx.environment.name} 上不存在键 {key!r}",
            )
        return ProviderResult.ok({key: value})
