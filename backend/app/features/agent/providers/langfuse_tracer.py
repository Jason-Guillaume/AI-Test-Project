"""Langfuse LLM 可观测埋点（no-throw）。

职责：为 Agent 的 LLM 调用（``ProductionLLMProvider``）提供 generation 级埋点，
记录模型、输入消息、输出内容、token 用量与错误状态，供 Langfuse UI 追踪与评估。

环境隔离约定（三环境）：
- 每个环境（development / test / production）使用独立的 Langfuse project，
  各持一套 ``LANGFUSE_PUBLIC_KEY`` / ``LANGFUSE_SECRET_KEY``，由部署侧环境变量
  或本地 ``.env`` 注入，密钥绝不进版本库；
- ``LANGFUSE_ENVIRONMENT`` 是 trace 上的 environment 标签，供 UI 按环境过滤。

红线（与 ``notify()`` 相同语义）：
- 未启用（``LANGFUSE_ENABLED=false``）或 key 不齐时，所有埋点为 no-op；
- 埋点自身的任何失败只记日志、绝不抛出，不阻塞 LLM 主流程；
- 记录内容 = 实际发给模型的内容（已过 sanitizer 脱敏），不额外触碰密钥。
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from app.shared.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def _build_client() -> Any | None:
    """构建 Langfuse 客户端单例；未启用或 key 不齐时返回 None。

    构建失败（如 SDK 版本不兼容、base_url 非法）只记日志并返回 None，
    保证埋点永远是 no-op 而不是启动障碍。

    Returns:
        Any | None: ``langfuse.Langfuse`` 实例，或 None（埋点关闭）。
    """
    if not settings.LANGFUSE_ENABLED:
        return None
    public_key = (settings.LANGFUSE_PUBLIC_KEY or "").strip()
    secret_key = (settings.LANGFUSE_SECRET_KEY or "").strip()
    if not public_key or not secret_key:
        logger.warning("LANGFUSE_ENABLED=true 但 key 未配置齐全，LLM 埋点保持关闭")
        return None
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=settings.LANGFUSE_BASE_URL,
            environment=settings.LANGFUSE_ENVIRONMENT,
        )
        logger.info(
            "Langfuse 埋点已启用（环境：%s，端点：%s）",
            settings.LANGFUSE_ENVIRONMENT,
            settings.LANGFUSE_BASE_URL,
        )
        return client
    except Exception as exc:  # noqa: BLE001 —— no-throw：客户端构建失败不阻塞启动
        logger.warning("Langfuse 客户端初始化失败（埋点关闭）：%s", exc)
        return None


def get_langfuse_client() -> Any | None:
    """返回进程内共享的 Langfuse 客户端；未启用时为 None。

    Returns:
        Any | None: Langfuse 客户端或 None；测试中可通过
        ``_build_client.cache_clear()`` 重置后重新按环境变量构建。
    """
    return _build_client()


@contextmanager
def llm_generation(
    *,
    name: str,
    model: str,
    input_messages: list[dict[str, str]],
    model_parameters: dict[str, Any] | None = None,
) -> Iterator[Any | None]:
    """LLM 调用的 generation 埋点上下文；埋点关闭时 yield None。

    用法：``with llm_generation(...) as gen:`` 包住真实 LLM 请求，
    成功后调用方自行 ``gen.update(output=..., usage_details=...)``；
    主流程抛出的异常会在此标记为 ERROR 后**原样向上抛**，绝不吞异常。

    Args:
        name: generation 名称（如 ``agent.generate_structured.intent``）。
        model: 模型名（来自 ModelConfiguration，不含任何密钥）。
        input_messages: 实际发送的消息列表（已过 sanitizer 脱敏）。
        model_parameters: temperature / max_tokens 等采样参数。

    Yields:
        Iterator[Any | None]: ``LangfuseGeneration`` 句柄，或 None（埋点关闭）。
    """
    client = get_langfuse_client()
    if client is None:
        yield None
        return
    # 手动管理 enter/exit：把 span 创建失败与主流程异常分开处理，
    # 前者吞掉（no-throw），后者标记 ERROR 后原样抛出。
    try:
        cm = client.start_as_current_observation(
            name=name,
            as_type="generation",
            input=input_messages,
            model=model,
            model_parameters=model_parameters or {},
        )
        gen = cm.__enter__()
    except Exception as exc:  # noqa: BLE001 —— no-throw
        logger.warning("Langfuse span 创建失败（忽略）：%s", exc)
        yield None
        return
    try:
        yield gen
    except Exception as exc:
        # 主流程异常：先尽力标记 ERROR，再原样抛出，不改变调用方语义。
        try:
            gen.update(level="ERROR", status_message=str(exc)[:500])
        except Exception:  # noqa: BLE001
            pass
        try:
            cm.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:  # noqa: BLE001
            pass
        raise
    try:
        cm.__exit__(None, None, None)
    except Exception as exc:  # noqa: BLE001 —— no-throw
        logger.warning("Langfuse span 结束失败（忽略）：%s", exc)


def update_generation(
    gen: Any | None,
    *,
    output: Any = None,
    usage: dict[str, Any] | None = None,
) -> None:
    """安全地回写 generation 的输出与 token 用量；gen 为 None 时 no-op。

    Args:
        gen: ``llm_generation`` yield 出的句柄（可能为 None）。
        output: 模型原始文本输出。
        usage: OpenAI 兼容的 ``usage`` 字段，将映射为 Langfuse 的
            ``usage_details``（input / output / total）。
    """
    if gen is None:
        return
    try:
        kwargs: dict[str, Any] = {"output": output}
        if usage:
            # OpenAI 字段名 → Langfuse usage_details 字段名。
            details = {
                "input": usage.get("prompt_tokens"),
                "output": usage.get("completion_tokens"),
                "total": usage.get("total_tokens"),
            }
            kwargs["usage_details"] = {k: v for k, v in details.items() if v is not None}
        gen.update(**kwargs)
    except Exception as exc:  # noqa: BLE001 —— no-throw
        logger.warning("Langfuse 回写失败（忽略）：%s", exc)


def flush_langfuse() -> None:
    """把队列中未上报的 trace 立即推送；应用停止期调用，失败只记日志。"""
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:  # noqa: BLE001 —— no-throw
        logger.warning("Langfuse flush 失败（忽略）：%s", exc)
