"""业务执行引擎包。

本包封装 Business Flow 的运行时能力：
- context.py：运行时上下文管理
- sensitive.py：敏感数据脱敏
- api_executor.py：HTTP API 执行器（复用 httpx）
- mapping_resolver.py：INPUT/OUTPUT 映射解析
- precondition_evaluator.py：前置条件评估
- output_extractor.py：JSONPath 输出提取
- business_flow_executor.py：主流程执行器

设计原则：
- 配置数据与运行数据分离（FlowExecution.context_json 存运行时变量）
- 不依赖 Celery/Redis，同步执行但代码结构支持未来迁移异步
- 复用 api_catalog 的 DebugService HTTP 能力，不重新实现 HTTP 请求逻辑
"""

from app.features.business.executors.context import ExecutionContext
from app.features.business.executors.sensitive import SensitiveDataMasker

__all__ = [
    "ExecutionContext",
    "SensitiveDataMasker",
]
