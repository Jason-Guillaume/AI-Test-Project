"""FAKER Provider（§9.4）：只调固定白名单方法生成假数据，不执行用户代码。

生成器白名单与 `${faker.phone}` 模板共用同一个入口
``variable_resolver.generate_faker_value``，保证 Fixture 步骤和用例数据不是两套
随机实现。结果写进私有变量的 ``output_key``（缺省用生成器名）。

locale 只允许 zh_CN / en_US；非法生成器与非法 locale 都是配置错误，
报 ``FIXTURE_INVALID``（locale）/ ``VARIABLE_RESOLVE_FAILED``（生成器）。
"""

from __future__ import annotations

from app.features.test_data.providers.base import (
    BaseProvider,
    ProviderContext,
    ProviderResult,
    config_of,
)
from app.features.test_data.runtime.variable_resolver import FAKER_LOCALES, generate_faker_value
from app.shared.errors import CODE_FIXTURE_INVALID, CODE_VARIABLE_RESOLVE_FAILED, AppError


class FakerProvider(BaseProvider):
    provider_type = "FAKER"

    def run(self, ctx: ProviderContext) -> ProviderResult:
        from app.features.test_data.schemas import FakerProviderConfig

        cfg = self.load_config(config_of(ctx), FakerProviderConfig)

        locale = (cfg.locale or "zh_CN").strip()
        if locale not in FAKER_LOCALES:
            raise AppError(
                f"FAKER locale 只允许 {'/'.join(FAKER_LOCALES)}，收到 {cfg.locale!r}",
                status_code=400,
                code=CODE_FIXTURE_INVALID,
            )

        try:
            value = generate_faker_value(cfg.generator, locale=locale, choices=cfg.choices)
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001 - Faker 内部异常收敛成统一错误码
            raise AppError(
                f"FAKER 生成失败（generator={cfg.generator}）：{exc}",
                status_code=400,
                code=CODE_VARIABLE_RESOLVE_FAILED,
            ) from exc

        key = (cfg.output_key or cfg.generator).strip()
        return ProviderResult.ok({key: value})


__all__ = ["FakerProvider"]
