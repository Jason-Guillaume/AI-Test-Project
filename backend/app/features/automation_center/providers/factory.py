"""按接入配置选择 CI Provider。"""

from __future__ import annotations

from collections.abc import Callable

from app.features.automation_center.models.entities import AutomationIntegrationConfig
from app.features.automation_center.providers.base import AutomationProvider, ProviderError
from app.features.automation_center.providers.jenkins_provider import JenkinsProvider
from app.features.automation_center.providers.yunxiao_provider import YunxiaoProvider

ProviderBuilder = Callable[[AutomationIntegrationConfig], AutomationProvider]


class ProviderFactory:
    """Provider 注册表；具体平台分支集中在此处。"""

    def __init__(self) -> None:
        self._builders: dict[str, ProviderBuilder] = {
            "YUNXIAO": YunxiaoProvider.from_config,
            "JENKINS": JenkinsProvider.from_config,
        }

    def register(self, provider_type: str, builder: ProviderBuilder) -> None:
        """注册新的 Provider 实现。"""
        self._builders[provider_type.strip().upper()] = builder

    def get(
        self,
        provider_type: str | None,
        config: AutomationIntegrationConfig,
    ) -> AutomationProvider:
        """获取对应 Provider；未注册的平台明确失败，不回退到云效。"""
        key = (provider_type or "YUNXIAO").strip().upper()
        builder = self._builders.get(key)
        if builder is None:
            raise ProviderError(f"暂不支持执行平台：{key or '未指定'}")
        return builder(config)


provider_factory = ProviderFactory()
