# 后端综合拆分总需求提示词

本文用于一次性委托完整的 B0–B9 后端重构，详细目标、路径和验收见 [18 综合工作包](18-backend-comprehensive-refactor-plan.md)。编制日期：2026-10-29。当前仅编制文档，未执行下面的代码任务。

## 可直接复制给 Agent

```text
请在当前项目完成一次覆盖主要后端领域的综合职责拆分。这是一个完整任务，不是只做 D1 或每做一点就等待我再次下指令。

项目路径：
/Users/a1/Desktop/ai-test-project

先完整阅读：
1. 综合计划与工作量：
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/18-backend-comprehensive-refactor-plan.md
2. 本次总需求：
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/19-backend-comprehensive-agent-prompt.md
3. 当前规范与已验证基线：
/Users/a1/Desktop/ai-test-project/docs/coding-conventions.md
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/backend-stabilization-delivery.md

如果 checkout 路径不同，按实际根目录定位上述文档，不把本机路径写入运行代码。

整单范围为 B0–B9 全部工作包：
B0 固定源码内容、接口/状态/事务及当前 1042 项通过记录的可比较测试基线。
B1 提取执行结果契约、用例数据/断言准备和 API/业务/Web 执行适配，消除跨领域私有函数依赖。
B2 拆任务运行创建、方案批准、命令服务，保留既有查询/消息/资源服务和唯一公开门面。
B3 拆完整任务处理器、租约/续租/恢复及完成/失败协调，保留状态、幂等、行锁和迟到结果保护。
B4 整理安全执行准备与结果持久化、ZAP 协议能力和扫描阶段、计划/任务服务，保留原队列、范围和人工批准。
B5 拆 API 目录的模块、接口、请求、关系、变更与响应转换，导入/调试使用公开契约。
B6 拆 Fixture 校验/依赖图、数据生成分派/上下文/记录与清理生命周期，复用现有 Provider 和模板引擎。
B7 收口 business 动作/流程执行、Web 页面/用例确认/认证/执行服务以及 Agent 定义/会话/治理协调边界。
B8 按资源拆大型 Schema 和必要 Router，统一 canonical exports、公开服务和跨域引用。
B9 完成完整回归、测试逐项对比、文档更新和统一交付。

保留现有 core/execution/llm/agents/tools/skills/mcp/features 顶层布局和全部已交付行为。R/C/T/E/F 已完成部分不重做。旧计划中“默认只做一个小阶段”“后续等待单独请求”的范围限制由本次 B0–B9 总需求覆盖。

按内部依赖持续实施，各包是你自己管理的工作单元，不需要每包结束再问我是否继续。常规实现选择自行决策，遇到本轮回归先修复，再继续后续包。持续维护进度记录；上下文压缩后继续完成整单，不重复盘点或以完成一个模块就结束。真实外部阻塞或需破坏性扩大范围时明确指出所需信息，不把测试失败或工作量大当作交付完成。

保留用户已有修改，固定基线时不要复制 .env/凭据/登录态，不使用全仓 reset/restore。保持原 API、字段、权限、人工确认、数据库、工作流/工具 key、快照、事务、外部回执和暂停/取消语义。各共享能力只有一份主体实现，不恢复已删除的旧兼容目录，不靠空壳、纯改名、万能 context/mixin 或复制业务逻辑来完成拆分。

不升级依赖、不新增框架或数据库迁移，不开发知识库/E5 工具/新 UI，不连接真实扫描目标或发送外部通知；前端只有受后端契约影响且无法避免时做最小修复，不顺带重构。

每包执行相关定向测试，在计划规定的跨域检查点和最终验收运行后端全量回归；未发生新变化时不无意义重复测试。测试使用隔离数据库、受控本地 HTTP/浏览器服务和 Fake/Mock 外部依赖。必须保护 F 阶段修复的 ZAP 装配、治理引用保护、HTTP null/UTF-8/总超时、pytest 收集与浏览器登录。

对照原 1042 项保存 nodeid 差异；移动/参数化测试必须提供覆盖映射，不删除、跳过或弱化真实测试。只有所有工作包实际落地、生产调用迁移完成且最终全量无失败/错误/异常跳过时，才声明整单完成。全量未通过时如实记录并继续处理本轮问题，不用编译或少量 smoke 代替验收。

执行中维护：
docs/agent-cluster-refactor/backend-comprehensive-progress.md
最终交付：
docs/agent-cluster-refactor/backend-comprehensive-delivery.md
保存各包路径/方法映射、公开契约、事务/回执边界、检查点结果、最终机器可读测试报告、warnings 分类、剩余限制和回退说明，并同步规范与索引。

请直接完成整单 B0–B9，不要只回复方案或只交付第一小步。若遇到真实运行限制，明确未完成工作并留下准确进度，不能把部分进展描述成综合拆分已完成。
```
