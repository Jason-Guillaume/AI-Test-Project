# core 归并实施 Agent 提示词

> 状态说明（2026-10-28）：本提示词记录已完成的 core 归并阶段要求，其中“保留旧路径兼容转发”已被后续明确的用户请求覆盖。不要据此重建已删除的纯转发文件；当前规范路径与清理范围见[core 归并交付记录](core-consolidation-delivery.md)。

本文保留可复制的实施要求，与 [10 优化计划](10-core-consolidation-plan.md) 配合使用。当前工作区的实际迁移和验证状态见 [core 归并交付记录](core-consolidation-delivery.md)；本提示词本身不替代代码与测试证据。

编制日期：2026-10-28。

## 可直接复制

```text
请对当前项目实施 models 与 shared 归并 core 的结构优化，完成实际代码修改、兼容处理与验证。

项目路径：
/Users/a1/Desktop/ai-test-project

先完整阅读以下文件：
1. 优化计划：
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/10-core-consolidation-plan.md
2. 本次执行要求：
/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/11-core-consolidation-agent-prompt.md
3. 仓库编码规范：
/Users/a1/Desktop/ai-test-project/docs/coding-conventions.md

如果实际 checkout 不在上述位置，使用实际仓库根目录解析同名文档，不把开发机路径写入运行代码。

目标：
把 backend/app/models 的平台核心模型与 backend/app/shared 的公共能力统一归到 backend/app/core，按 config、database、models、security、http、notifications 划分。Agent、Skill、MCP、工具和各 Feature 的模型继续保持现有归属。

实施顺序：
按计划中的 C0–C5 分批推进：核对基线；迁移配置和数据库；迁移核心模型；分类迁移公共能力；更新调用方；完成回归与交付。直接迁入计划中的最终路径，不增加临时目录再二次搬迁。保留用户已有修改，不重置或覆盖无关工作。

必须满足：
- Base、metadata、engine、SessionLocal、settings、核心 ORM 类、依赖函数及公共可变状态只有一份规范实现；旧新路径指向同一对象。
- core/__init__.py 保持轻量，Base 模块独立，不因导入 core 自动加载上层业务或初始化数据库连接池。保留现有配置与 session 初始化策略、环境变量优先级和脚本设置数据库地址的顺序。
- core 不反向依赖 agents、tools、skills、mcp、knowledge 或 features。原 app.models 的上层能力历史名称继续留旧入口懒加载，不能搬进 core/models 形成反向依赖。
- app.models 和 app.shared 的旧路径保留必要的单向兼容转发。原 Agent/业务脱敏等更早的兼容入口也必须继续指向同一实现。
- 不修改历史 Alembic 迁移，不改数据库表、字段、约束和数据，不为文件移动新增迁移。历史 0001 的旧导入、基线九表白名单及后续显式建表必须继续有效；当前 Alembic 装配保留完整模型发现。
- 不改变 API、认证授权、角色、错误信封、Session flag、分页、限流、通知事务与脱敏行为，不升级依赖，不扩展知识库或任务功能。
- 检查脚本、测试 fixture、monkeypatch 和 dependency_overrides 的真实绑定位置；不能通过跳过测试、弱化断言或使用另一套实现掩盖回归。

验证：
按优化计划完成新旧对象一致性、多种导入顺序、轻量初始化、脚本配置顺序、核心 HTTP 行为、上层模块及隔离库迁移验证，收尾运行后端完整回归。数据库验证使用显式配置的隔离测试库，不清空开发/生产库，不把凭据输出到日志。缺少环境时记录未测范围并继续完成不依赖该环境的工作，不能把编译通过、OpenAPI 可生成或 alembic heads 视为行为回归通过。

交付：
创建 docs/agent-cluster-refactor/core-consolidation-delivery.md，列出完成阶段、实际路径映射、兼容入口及保留原因、真实测试命令和结果、已知限制与回退方式。同步更新编码规范、受影响的设计路径和文档索引，保留前轮交付记录的历史事实。

请直接实施，不要只给方案或只移动文件。必要验证未完成时如实标记，不宣称 C0–C5 已全部验收。
```
