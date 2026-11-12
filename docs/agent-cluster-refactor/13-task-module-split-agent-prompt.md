# 任务模块拆分需求提示词

本文供下一位实施 Agent 直接使用；详细范围、路径与验收见 [12 任务模块拆分计划](12-task-module-split-plan.md)。本次仅交付文档，未执行下面的代码任务。

编制日期：2026-10-28。

## 可直接复制

```text
请在当前项目实施任务模块职责拆分，完成实际代码修改、兼容处理、测试和交付记录。

项目路径：
/Users/a1/Desktop/ai-test-project

先完整阅读：
1. 计划文档：
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/12-task-module-split-plan.md
2. 本次执行要求：
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/13-task-module-split-agent-prompt.md
3. 编码规范及前轮实际验证：
/Users/a1/Desktop/ai-test-project/docs/coding-conventions.md
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/core-consolidation-delivery.md

若当前 checkout 位于其他路径，请使用实际根目录定位相同文档，不把开发机绝对路径写入运行代码。

默认范围为 T0–T3：
- T0：重新复现和分类前轮测试失败，修复与任务链路和公共导入有关的阻塞，建立可信行为基线；不把历史失败全部认定为无关问题。
- T1：从 TaskService 提取任务/运行/消息/事件查询、纯响应转换和任务访问检查，保留原公开入口。
- T2：提取消息及资源服务，保留消息幂等、接收对象、可能的新运行创建、事件、来源回链和批量名称查询。
- T3：定义明确的窄处理契约，提取报告和审阅 handler，Worker 负责原有执行控制并调用新实现。

主要代码位置：
backend/app/features/tasks/services/task_service.py
backend/app/features/tasks/runtime/worker.py
目标文件与方法映射按计划第 3、4 节执行。T4–T6 的运行创建、方案批准、命令、其余处理器及租约恢复属于后续阶段，本轮不提前整体迁移，不建立空壳。

约束：
保留已有改动，不重置工作区。任务业务仍归 features/tasks，模型生成仍归 agents，能力操作复用现有 tools 和业务服务。core 已归并，不重做公共底座，不修改前端，不新增框架、数据库结构或依赖升级。

保留 API、状态、快照、工具 key、调用回执键、权限、人工确认、消息去重和现有提交边界。报告会真实写入业务产物，不把 handler 一律改成无 commit 或全部独立 commit；先核对原提交、外部 IO、回执和控制顺序，再迁移。审阅继续以正式事实和确定性校验约束模型输出，保留模型调用后的暂停/取消和陈旧尝试保护。

新子模块不得反向导入 TaskService 或整个 Worker。需要运行创建、工具授权、模型、入队、事件和控制边界时通过明确的窄接口协调，不能依赖万能上下文、私有方法集合或复制实现。

按阶段执行必要验证，补充缺少的权限、幂等、真实产物、审阅事实和暂停/取消回归，最后运行后端全量测试。使用显式配置的隔离 PostgreSQL，不操作开发/生产库，不把凭据写入文档或日志。不能跳过失败测试、弱化断言、伪造成功，或用编译/OpenAPI 通过替代行为验证。环境受限或基线失败保留时，记录具体证据和受阻阶段，不宣称全量通过。

完成后创建：
docs/agent-cluster-refactor/task-module-split-delivery.md
列出 T0 基线与修复、完成阶段、实际路径/方法映射、事务和回执边界、真实测试结果、兼容入口、未完成项和回退方式，并同步相关文档索引。

请直接实施 T0–T3，不要仅输出方案或机械搬文件；真实调用必须切换到唯一的新实现。T4–T6 及前端拆分只记录后续待办。
```
