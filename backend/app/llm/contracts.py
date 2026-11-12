"""模型调用协议与错误契约。

为 Agent、报告、Web 和任务域提供稳定调用类型；不包含模型配置、授权或工作流逻辑。
"""

from __future__ import annotations

from typing import Any, Callable, Protocol


class LLMError(Exception):
    """携带调用错误码、可恢复标记和不含请求正文的候选尝试记录。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        attempts: list[dict[str, Any]] | None = None,
    ) -> None:
        """保存调用层需要的错误信息，不记录提示词、响应正文或密钥。"""
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.attempts = attempts or []


class LLMProvider(Protocol):
    """结构化生成与普通对话协议，允许领域注入 Fake Provider。"""

    def generate_structured(
        self,
        system: str,
        user_content: str,
        schema: dict[str, Any] | None = None,
        *,
        kind: str | None = None,
        history: list[dict[str, str]] | None = None,
        validator: Callable[[dict[str, Any]], Any] | None = None,
    ) -> dict[str, Any]:
        """生成结构化 JSON 字典；具体校验和失败语义由 Provider 保持。"""
        ...

    def chat(
        self,
        system: str,
        user_content: str,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """生成普通文本回复。"""
        ...


__all__ = ["LLMError", "LLMProvider"]
