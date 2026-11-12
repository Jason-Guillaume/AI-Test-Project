# 业务域共享能力提取需求提示词

本文是可复制给实施 Agent 的需求，与 [14 共享能力提取计划](14-business-capability-extraction-plan.md) 配合使用。编制日期：2026-10-29。本次仅交付文档，未执行下述代码任务。

## 可直接复制

```text
请在当前项目实施业务域共享能力提取，完成实际代码修改、调用方迁移与验证。

项目路径：
/Users/a1/Desktop/ai-test-project

先完整阅读：
1. 优化计划：
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/14-business-capability-extraction-plan.md
2. 本次需求：
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/15-business-capability-agent-prompt.md
3. 编码规范与当前交付状态：
/Users/a1/Desktop/ai-test-project/docs/coding-conventions.md
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/task-module-split-delivery.md

若实际 checkout 不在上述位置，按实际仓库根目录解析同名文档，不在代码中硬编码开发机路径。

默认执行 E0–E4：
E0 核对最新代码、引用、已删除兼容路径、当前测试基线与行为差异。
E1 将 business 下被多领域复用的 HTTP 执行能力提取到 app/execution/http，并使接口调试及业务/测试/安全/造数调用同一规范发送实现。
E2 将纯 JSON/字典路径读取、已确认一致的比较基础操作提取到 core/expressions，保留业务前置条件和测试断言的不同语义。
E3 将通用模型 Provider、结构化调用、候选链和追踪提取到 app/llm，让 Agent、报告、Web、任务依赖公开协议；模型配置和授权仍归原模块，报告提示词归报告领域。
E4 将现有唯一模板解析器迁到 app/execution/templates，保持算法、上下文、Faker 生成时机并收口所有实际调用方。

E5 新业务工具属于独立功能阶段，本轮仅输出建议契约，不自动注册或开放。不要扩展前端、知识库、任务 T4–T6、数据库结构或依赖版本，不重写原业务执行器。

必须保持：
- HTTP 的项目出站授权、显式放行的内网目标、trust_env=False、禁止重定向、超时、流式截断、请求覆盖顺序和错误语义。调试特有 outbound_target_id 及错误返回由适配层保持；LLM/MCP/飞书/ZAP 控制连接不强塞进被测目标通道。
- None、缺失值、IN 空项、未知操作符和数值比较的原领域语义；不能把不同的比较函数直接互换。测试、安全和业务结论仍在各领域。
- 模型配置权限、凭据加密/脱敏、默认/候选链、结构校验、错误、尝试回调和工具调用限制；llm 不依赖 Agent 图、任务或报告内部实现。
- 模板命名空间、类型保留、缺失/required、递归限制、Header 大小写和 Faker 白名单，不新增缓存或另一套解析器，不从引擎查询业务数据库。
- 既有 API、数据、工具 key、工作流、任务状态、回执、事务、人工确认及暂停/取消行为。

保留已有改动，不重置工作区；已清理的 app.shared/app.models/features.agent 等旧兼容目录不要恢复。内部调用直接迁到规范路径，仅对有真实消费者的公开契约保留最小门面并记录原因，禁止新旧主体双份维护。

按阶段运行相关定向验证，针对实际风险补行为测试，收尾运行后端全量回归。使用隔离数据库、Mock HTTP 和 Fake/Mock LLM，不操作开发/生产库，不发真实扫描/通知/模型请求，不记录明文凭据。对历史失败重新复现，区分新增失败、基线失败与未测项，不通过跳过测试、弱化断言或伪造成功宣称全绿。

完成后创建：
docs/agent-cluster-refactor/business-capability-extraction-delivery.md
列明 E0 基线、E1–E4 路径/符号映射、语义承接、真实测试结果、保留门面、未完成项、回退方式和 E5 后续工具契约，并更新编码规范及文档索引。

请直接实施 E0–E4，不要仅输出方案或机械搬文件；共享能力必须由真实调用方使用，不能只创建目录或 registry 项就标记完成。
```
