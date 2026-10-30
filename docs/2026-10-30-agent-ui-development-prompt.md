# 可直接交给开发 Agent 的需求提示词

请在现有项目 `/Users/a1/Desktop/ai-test-project` 内，实际完成 Agent 工作台体验优化与功能增强，不要只输出分析、建议或原型。

先阅读适用的 AGENTS.md，并依次阅读以下文档：

1. 完整实施方案：`/Users/a1/Desktop/ai-test-project/docs/2026-10-30-agent-ui-implementation-plan.md`。
2. 问题审查证据：`/Users/a1/Desktop/ai-test-project/docs/2026-10-30-agent-ui-optimization-review.md`。
3. 启动指南：`/Users/a1/Desktop/ai-test-project/local-startup-guide.md`。
4. 既有业务边界参考：`/Users/a1/Desktop/ai-test-project/docs/testing-workflow-optimization-handoff.md`。

以当前源码为准复核现状，保护工作区已有未提交改动。按完整实施方案连续完成 A→B→C→D：先修复零选误确认、跨项目会话残留、异步响应污染、消息失败丢失和错误态；再简化导航、任务创建、Agent/任务工作区、结果展示与响应式布局；随后实现真实的待我处理中心、任务模板与再次执行；最后完成运行对比和失败→缺陷→验证任务的闭环。已经具备的暂停、恢复、工作项重试、失败聚类与产物追溯必须复用。

保留现有技术栈、专业编辑能力、路由深链接、权限和人工审批边界。新功能必须包含真实服务端、持久化、前端交互和必要测试，不使用假数据或空按钮交付。不要重写执行引擎、另建网站或顺带实现方案明确排除的后续功能。正常技术选择自行决定并记录，不在每阶段结束后停下来等待确认；缺少外部环境时记录具体阻塞并继续独立工作，不虚报完成。

先建立简短执行清单，随后直接编码。按方案验证关键行为、前端测试/lint/typecheck/build、受影响后端测试及隔离库迁移；对登录后的关键工作流做 1440/1024/768/390px 浏览器验收。不能用旧测试记录或静态检查代替本次实际验证。

持续维护 `/Users/a1/Desktop/ai-test-project/docs/agent-ui-optimization-progress.md`，最终生成 `/Users/a1/Desktop/ai-test-project/docs/agent-ui-optimization-delivery.md`，验收证据放在 `/Users/a1/Desktop/ai-test-project/docs/agent-ui-optimization-validation/`。最终逐项报告 A–D 的完成情况、实际改动文件、测试结果和未解决限制。
