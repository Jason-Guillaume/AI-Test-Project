# 后端修复与回归收尾需求提示词

本文可直接交给实施 Agent，与 [16 修复与后续拆分计划](16-backend-stabilization-and-split-plan.md) 配合使用。编制日期：2026-10-29。本次只交付文档，未执行下述修复。

## 可直接复制

```text
请在当前项目实施后端问题修复与回归收尾，完成实际代码修改、测试和交付记录。

项目路径：
/Users/a1/Desktop/ai-test-project

先完整阅读：
1. 修复及后续拆分计划：
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/16-backend-stabilization-and-split-plan.md
2. 本次需求提示词：
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/17-backend-stabilization-agent-prompt.md
3. 编码规范与前轮交付：
/Users/a1/Desktop/ai-test-project/docs/coding-conventions.md
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/business-capability-extraction-delivery.md

若实际 checkout 位于其他路径，使用实际根目录解析同名文件，不硬编码开发机路径。

默认执行 F0–F4：
F0 修复前采集当前逐项测试基线，保存 nodeid、错误分类、代码状态和运行命令；历史没有清单的项目标为来源未知，不用 pytest lastfailed 缓存代替本次报告。
F1 修复 ZAP 路由挂载和 ScanWorker 生命周期接线；核对唯一消费所有者、配置开关和退出释放。修复治理 Router 对不存在服务方法的调用，复用 agents 服务中的跨能力协调，恢复 Skill 更新、删除和版本恢复的引用保护。
F2 修复共享 HTTP 的显式 JSON null 发成空 body、UTF-8 跨块损坏及慢响应绕过总时长限制；保持出站授权、代理/重定向策略、截断和各领域错误契约。
F3 收口 Web 草稿 Provider 的真实测试注入位置、AGENT_INTENTS 的规范导入和 pytest 误收集；定位浏览器登录跳转超时，逐族复核剩余 ZAP/审批/Web/治理失败并最小修复。
F4 完成定向和后端全量回归，保存逐项差异、剩余问题、警告分类及真实交付状态。

HTTP 测试必须验证真实 HTTPX 编码后的 request.content/headers，并覆盖实际流边界；不能只检查 FakeClient 的 kwargs。总时长必须能按剩余预算中止阻塞读取，不能只在聚合 chunk 返回后检查时钟；超时按现有 timeout 错误路径处理并释放连接。

Skill 恢复/统计/删除和 MCP 删除的协调逻辑已存在于 agents/services/agent_service.py。使用正确公开入口并保留引用检查，不通过给 skills/mcp 补无保护别名掩盖错误。路由、Worker 开关、真实行为均需测试，不能只验证 import 和 OpenAPI 生成。

保持已有 API、角色、权限、数据库结构、事务、任务回执、人工审批和暂停/取消语义；保留用户已有修改，不重置工作区、不修改历史迁移、不升级依赖、不恢复已删除的旧兼容目录。

测试使用显式配置的隔离 PostgreSQL、Fake/Mock 模型和扫描连接器、受控本地 HTTP/浏览器服务；不操作开发/生产库，不发真实扫描或外部通知，不记录明文凭据。不能跳过真实测试、弱化断言、伪造成功或通过任意延长超时掩盖问题。

报告明确区分已修复、仍失败、新出现、未收集/未执行和无法判定来源的项目。只在本次全量真实通过时声明全量通过，未完成的项目如实记录。

创建：
docs/agent-cluster-refactor/backend-stabilization-delivery.md
并按计划保存脱敏后的机器可读测试清单，更新相关文档索引和实际运行说明。

请直接实施 F0–F4，不要只输出方案。计划中的 D1–D4 目录优化本轮仅整理待办，先完成修复与行为验收，再单独实施执行契约、任务运行控制、安全域和 API/schema 拆分。
```
