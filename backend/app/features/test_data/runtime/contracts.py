"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GenerationResult:
    """一次生成的结果。``outputs`` 是**未脱敏**的契约输出，调用方注入上下文用。"""

    data_execution_id: int
    status: str
    outputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
