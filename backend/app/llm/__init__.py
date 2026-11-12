"""通用模型调用契约；具体 Provider 与 Agent 编排分层装载。"""

from app.llm.contracts import LLMError, LLMProvider

__all__ = ["LLMError", "LLMProvider"]
