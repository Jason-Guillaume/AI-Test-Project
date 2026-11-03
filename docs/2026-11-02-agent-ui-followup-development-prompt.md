# 第二轮整改开发提示词

请在现有项目 `/Users/a1/Desktop/ai-test-project` 中实际完成 Agent 工作台第二轮整改，不要只输出分析、建议或原型。

先阅读适用 AGENTS.md，并阅读以下文档：

1. 本轮完整方案：`/Users/a1/Desktop/ai-test-project/docs/2026-11-02-agent-ui-followup-implementation-plan.md`。
2. 问题与复现证据：`/Users/a1/Desktop/ai-test-project/docs/2026-11-02-agent-ui-followup-review.md`。
3. 启动指南：`/Users/a1/Desktop/ai-test-project/local-startup-guide.md`。

以当前源码为准复核，保护已有未提交改动。先建立简短执行清单，再直接开发，连续完成方案内 R1–R9：保留未展开高级设置中的预设 Agent；统一真实模型阻塞状态与待办分类；修复任务/缺陷创建失败重试的幂等性；确保缺陷验证环境一致；隔离项目切换后的运行对比、缺陷操作和待办页码；完善停用模板读取、名称说明与配置编辑；防止共享模板并发覆盖；将 Agent 计划、执行和分析改成默认结构化摘要；完成中等宽度与小屏布局。

复用现有技术栈、业务服务和权限/审批机制，不重新建设已完成功能，不扩展新业务模块。正常实现选择自行决定并记录，不在每个阶段结束后等待确认。对已修复项给出当前证据，避免重复修改；确有外部依赖阻塞时说明原因，并继续其他独立工作。

关键回归必须验证真实行为：折叠设置套用模板、模型耗尽写入真实状态后进入待办、服务端已提交但客户端响应丢失后的重试、跨项目切换、停用模板编辑、两个独立会话的模板并发冲突、缺陷验证更换环境。不能只改测试预期、匹配源码字符串或引用历史通过结果。运行前端测试/lint/typecheck/build、隔离数据库中的受影响后端回归，并保存 1440/1024/768/390px 登录态浏览器验收证据。

持续维护 `/Users/a1/Desktop/ai-test-project/docs/agent-ui-followup-progress.md`，最终生成 `/Users/a1/Desktop/ai-test-project/docs/agent-ui-followup-delivery.md`；脱敏验证证据放到 `/Users/a1/Desktop/ai-test-project/docs/agent-ui-followup-validation/`。最终逐项报告 R1–R9 实现情况、修改文件、实际验证结果和剩余阻塞。未执行的验证明确标记，不能宣称全部通过。
