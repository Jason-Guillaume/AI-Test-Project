"""共享 HTTP 执行契约。

定义领域适配器之间传递的执行结果；接口调试、业务流程及测试执行保留各自错误响应。
"""

from __future__ import annotations


class HttpExecutionResult:
    """保存一次 HTTP 发送的状态、响应和传输错误类别。"""

    __slots__ = (
        "status_code", "response_body", "response_headers", "response_time_ms",
        "request_url", "error_message", "transport_error_kind", "transport_error_detail",
    )

    def __init__(self) -> None:
        """初始化空响应；调用方按原领域契约决定如何呈现错误。"""
        self.status_code: int = 0
        self.response_body: str = ""
        self.response_headers: dict[str, str] = {}
        self.response_time_ms: int = 0
        self.request_url: str = ""
        self.error_message: str | None = None
        self.transport_error_kind: str | None = None
        self.transport_error_detail: str | None = None

    @property
    def success(self) -> bool:
        """按既有业务执行口径判断 2xx/3xx 响应是否成功。"""
        return self.error_message is None and 200 <= self.status_code < 400


# 原业务执行结果名保留为同一类型别名，避免恢复旧模块或维护第二份实现。
ApiRequestResult = HttpExecutionResult

__all__ = ["ApiRequestResult", "HttpExecutionResult"]
