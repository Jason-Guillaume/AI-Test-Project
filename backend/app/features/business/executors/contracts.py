"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from dataclasses import dataclass, field
from app.execution.http.contracts import HttpExecutionResult
from app.features.business.models.business_binding import BusinessBinding
from app.features.api_catalog.models.api_interface import ApiInterface


@dataclass
class ActionRunResult:
    """单个业务动作的执行结果（内存对象，不落库）。

    Data Factory 的 BUSINESS_ACTION Provider 消费它；``execute_action`` 只是把它
    的字段搬到 ``ActionExecution`` 行上。快照已脱敏，错误码沿用执行器既有口径。
    """

    status: str = "FAILED"
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int | None = None
    outputs: dict[str, object] = field(default_factory=dict)
    input_context: dict[str, object] = field(default_factory=dict)
    output_context: dict[str, object] = field(default_factory=dict)
    request_snapshot: dict | None = None
    response_snapshot: dict | None = None
    binding_id: int | None = None
    unverified_preconditions: list[dict] = field(default_factory=list)
    # 仅在测试适配时用于原始断言；内存响应不写入业务记录。
    http_result: HttpExecutionResult | None = None
    is_web: bool = False
    web_sensitive_values: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PreparedActionTarget:
    """只读动作目标；让调用方在生成用例数据前完成绑定检查，不持有执行资源。"""

    binding: BusinessBinding | None = None
    interface: ApiInterface | None = None
    error_code: str | None = None
    error_message: str | None = None

    @property
    def is_web(self) -> bool:
        """表示已选择的默认 Web 绑定。"""
        return self.binding is not None and self.binding.binding_type == "WEB"
