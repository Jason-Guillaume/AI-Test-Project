# Langfuse 优化实施提示词

将下文交给可访问本仓库的编码助手。

请在 /Users/a1/Desktop/ai-test-project 实施 Langfuse 追踪优化。先阅读 /Users/a1/Desktop/ai-test-project/docs/langfuse-optimization-plan.md，核对当前分支的实现、测试和实际安装的 SDK 版本。按以下顺序完成修改和验证。

1. 检查 backend/app/llm/tracing.py、子 Agent 运行入口，以及 planning.py、case_generation.py 中的上下文传播。构造两个实际并行的分支，覆盖嵌套模型调用、单分支失败重试和退出后的上下文恢复。断言导出数据的 trace ID 和直接父 ID。如复现断链，在并行或恢复边界修复，复用现有 span 和可信服务端身份。
2. 统一输入和输出的采集策略。生产默认仅记录允许的元数据，异步任务保留隐藏正文的行为。开发环境显式开启后才采集脱敏的同步调用正文。用虚构标记检查 generation、工具、异常和投递载荷，验证模型、用量、耗时和错误类型可查询。
3. 核查 backend/app/orchestration/tasks/services/trace_projection_service.py 的重试、去重和读取延迟处理，复用已有投递机制。确认 SDK 的建链、回写、flush 和查询兼容性，固定验证过的依赖版本。
4. 运行方案中的两份测试及改动影响的用例。验证 SDK 故障时成功和失败业务的原有语义。已有授权测试项目时，使用合成任务按 trace ID 读回验证；缺少连接条件时，完成本地导出验证，并列出待在线确认的项目。
5. 交付修改文件路径、实际复现的问题、修复内容、测试命令及结果、在线验证状态和回退步骤。示例和报告只使用合成数据及脱敏标识。
