# Langfuse 追踪优化方案

目标是从一条任务追踪中定位哪个 Agent、哪次调用失败，核对 token 用量，并控制发送到 Langfuse 的正文。以下是代码审查后的建议，并行链路和实际部署状态尚待验证。

## 1. 验证并行任务的父子关系

[planning.py](../backend/app/orchestration/tasks/runtime/handlers/planning.py) 和 [subagents.py](../backend/app/agents/runtime/subagents.py) 会传递父 span ID。[tracing.py](../backend/app/llm/tracing.py) 的 runtime_agent_context 恢复业务 ContextVar，而通用工具和模型埋点依赖 SDK 当前的 OpenTelemetry 上下文。metadata 中 task_id 相同，只能证明业务关联。[SDK 上下文说明](https://langfuse.com/docs/observability/sdk/instrumentation)

先构造两个并发子 Agent，让一个分支失败后重试。对照预期树与实际导出的 trace ID、observation ID 和直接父 ID。若复现断链，在跨线程或恢复执行的入口绑定来自服务端运行记录的追踪上下文，退出后恢复。线程内沿用当前活动 span，避免模型调用跳过中间工具节点。对照 [case_generation.py](../backend/app/orchestration/tasks/runtime/handlers/case_generation.py) 已有的显式 trace_context 逻辑，避免重复创建 observation。

验收要求是两个分支共享任务 trace，各自的直接父节点正确，失败与重试可区分。随后执行的另一条任务应归入自己的 trace。

## 2. 统一正文采集

当前 llm_generation 和 update_generation 根据 task_trace_metadata 是否有值决定是否发送正文。建议在 [config.py](../backend/app/core/config.py) 定义显式采集设置，让输入和输出走同一决策。生产默认仅发送允许的元数据，异步任务保留现有隐藏正文的行为。开发环境如需查看同步调用正文，显式开启并对输入、输出分别脱敏。

用带唯一标记的虚构输入、输出和异常测试有上下文、无上下文及异常退出的路径。检查实际导出的 generation、工具属性、异常事件及运行事实载荷。默认策略下标记应为零命中，模型名称、错误类型和可获得的 token 用量仍可查询。

## 3. 固定兼容版本并验证投递

[requirements.txt](../backend/requirements.txt) 允许 langfuse>=3,<6。记录当前运行版本，验证建链、generation 回写、flush 和查询接口后固定通过验证的版本。[trace_projection_service.py](../backend/app/orchestration/tasks/services/trace_projection_service.py) 已处理重试及服务端读取延迟。复用现有状态检查失败数和最老待投递记录的等待时间。模拟提交成功但响应丢失，验证重试后同一 projection_key 对应一条投递事实。

## 验证与发布

在仓库根目录运行以下定向回归，并补充并行归属和正文策略用例。

    backend/.venv/bin/python -m pytest backend/tests/test_27_langfuse_tracing.py backend/tests/test_62_trace_projection.py

在独立测试项目执行上述合成任务，等待数据可读取后按 trace ID 核对父节点、重试、用量和正文。模拟 SDK 不可用，验证成功任务仍成功、失败任务仍返回原业务异常。记录脱敏的 ID 对照、版本、命令及结果。缺少服务端条件时，把在线读回列为待验项。

通过测试环境验收后按环境发布。出现采集异常时，关闭对应环境的 LANGFUSE_ENABLED 并按部署方式重启相关进程，核查已有投递积压。

[配套实施提示词](langfuse-optimization-prompt.md)
