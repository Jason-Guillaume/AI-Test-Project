"""请求上下文：请求 ID 解析与日志注入。"""

from __future__ import annotations

import contextvars
import logging
import re
import uuid

# 上下文变量：存放当前请求 ID，供请求中间件、业务代码与日志过滤器在异步调用链里共享。
request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

# 允许的请求 ID 形态：8-128 位字母数字与 . _ -；超出该形态的值会被丢弃并重新生成。
REQUEST_ID_PATTERN = r"[A-Za-z0-9._-]{8,128}"

# 日志格式：固定带 [request_id] 段，便于把一次请求的全部日志串成同一条链路。
LOG_FORMAT = "%(asctime)s %(levelname)s [%(request_id)s] %(name)s %(message)s"


def _valid_id(value: str) -> bool:
    """判断请求头里的 X-Request-ID 是否为可用值。

    用 fullmatch 严格匹配 REQUEST_ID_PATTERN：不合法（含过短、含特殊字符、空串）一律
    视为非法，调用方随之生成新的随机 ID，避免脏值进入日志与错误信封。
    """
    return bool(re.fullmatch(REQUEST_ID_PATTERN, value))


def resolve_request_id(incoming: str | None) -> str:
    """解析请求链路 ID：取请求头中的 X-Request-ID，格式非法时生成新的 hex。

    Args:
        incoming: 客户端传入的 X-Request-ID；为 None 或空白时视为未提供。

    Returns:
        str: 可直接用于日志与错误信封的 ID（保留原值或新生成的 32 位 hex）。
    """
    value = (incoming or "").strip()
    return value if _valid_id(value) else uuid.uuid4().hex


class RequestIdFilter(logging.Filter):
    """把当前请求 ID 注入日志记录，便于跨模块串起同一次请求的链路。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """给日志记录补 request_id 字段并截断显示长度。

        Args:
            record: 标准库的日志记录对象，会被原地写入 request_id 属性。

        Returns:
            bool: 恒为 True，只做字段注入，不过滤任何日志。
        """
        value = str(getattr(record, "request_id", "") or "-")
        # 日志里只保留前 8 位，控制单行长度；完整 ID 仍在 request.state 上供错误信封使用。
        record.request_id = value[:8]
        return True


def configure_logging() -> None:
    """补充标准输出处理器；宿主（uvicorn）已配置日志时不重复追加。"""
    root = logging.getLogger()
    # 幂等保护：宿主进程已配置过处理器时直接返回，避免重复输出同一行日志。
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)


__all__ = [
    "LOG_FORMAT",
    "REQUEST_ID_PATTERN",
    "RequestIdFilter",
    "configure_logging",
    "request_id_context",
    "resolve_request_id",
]
