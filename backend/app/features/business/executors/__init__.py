"""业务执行引擎包。

本包封装 Business Flow 的运行时能力：
- context.py：运行时上下文管理
- HTTP 请求由 app.execution.http 的唯一共享执行器承担
- mapping_resolver.py：INPUT/OUTPUT 映射解析（路径读取复用 core.expressions）
- precondition_evaluator.py：前置条件评估
- business_flow_executor.py：主流程执行器

设计原则：
- 配置数据与运行数据分离（FlowExecution.context_json 存运行时变量）
- 不依赖 Celery/Redis，同步执行但代码结构支持未来迁移异步
- 业务映射留在 business，通用 HTTP 发送与路径读取分别归共享能力层
"""

from app.features.business.executors.context import ExecutionContext
from app.core.security.sensitive import SensitiveDataMasker

__all__ = [
    "ExecutionContext",
    "SensitiveDataMasker",
]
