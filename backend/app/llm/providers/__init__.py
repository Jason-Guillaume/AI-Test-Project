"""OpenAI 兼容 Provider 实现；候选链行为仍由 ProductionLLMProvider 负责。"""

from app.llm.providers.openai_compatible import FakeLLMProvider, ProductionLLMProvider

__all__ = ["FakeLLMProvider", "ProductionLLMProvider"]
