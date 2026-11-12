# features 目录归属优化建议

> 后续状态：第一轮 platform/orchestration 迁移已实施，见 [目录布局交付](features-directory-layout-delivery.md)。Web、Mock 与工具职责的进一步复核见 [21 能力边界与命名方案](21-capability-boundaries-and-naming-plan.md)；其中 web_testing、mocking、浏览器运行时与智能体编写能力的建议修订本文原先的保留判断。下文保留第一轮核对时的方案语义。

核对日期：2026-10-29。基于当前工作区源码的静态检查；本轮未修改源码、未运行回归测试。现有工作区含大量未提交的重构改动，以下映射是待实施方案。

## 判断

`backend/app/features/` 当前有 18 个直接子模块。问题主要是平台管理、任务编排和测试业务并列，而非每个模块都需要继续拆小。

现有综合拆分已经将 TaskService/Worker、安全执行、Fixture、Web 服务以及多个 router/schemas 拆成职责较小的实现。本轮宜先调整包归属，保留叶子包名称、公开服务和内部执行链，避免重复拆分。

## 建议目录与完整迁移映射

```text
backend/app/
├── main.py                          # HTTP 路由及生命周期的装配入口
├── core/                            # 通用配置、数据库、安全、HTTP 等底座
├── platform/                        # 平台管理和管理端能力
│   ├── users/
│   ├── organizations/
│   ├── projects/
│   ├── environment_configuration/
│   ├── model_configuration/
│   ├── notifications/
│   └── agent_governance/             # 聚合已有 Agent/Skill/MCP/Tool 管理接口
├── orchestration/
│   └── tasks/                       # 任务状态、命令、租约、调度和业务适配
├── features/                        # 测试产品的业务能力
│   ├── api_catalog/
│   ├── business/
│   ├── mock_management/
│   ├── security_testing/
│   ├── test_data/
│   ├── test_management/
│   ├── web_ui/
│   ├── defects/
│   ├── reports/
│   └── dashboard/
├── execution/                       # 已有通用 HTTP 执行与模板解析
├── agents/
├── llm/
├── tools/
├── skills/
└── mcp/
```

`platform/` 下的 7 个叶子包从 `features/` 原名迁入；`features/tasks/` 迁入 `orchestration/tasks/`；其余 10 个 feature 原地保留。新包初始化保持轻量，避免导入一个平台模块时加载全部路由和业务模型。

`platform` 是目录分类，不改变接口使用者和原有鉴权：例如通知收件箱仍供普通用户使用，项目环境仍保留现有只读选项与管理接口的权限差异。平台管理服务不进入 `core/`；核心 9 张基线表的 ORM 所属本轮不变。

## 哪些职责值得继续拆，哪些先保留

| 位置 | 源码观察 | 建议 |
|---|---|---|
| `agent_governance/router.py` | 实现只剩聚合路由，调用 agents、skills、mcp 等公开服务 | 迁到 platform；暂时保留统一 `/agent-governance` 接口，不再建立一套治理业务层 |
| `tasks/` | 任务状态、调度与 API/Web/安全/报告处理器共同组成编排层 | 整包迁入 orchestration；handlers 继续归编排，不迁入 agents |
| `web_ui/services/session_service.py` | 创建任务浏览器会话时读取 Task、TaskRun、TaskAgentInstance；tasks 又调用 Web 服务 | 如继续做职责优化，优先整理这条双向依赖。将运行/参与者绑定校验收口到上层协调或注入的窄校验接口；独立 Web 入口也必须保持相同校验，不能只在任务调用处检查 |
| `model_configuration/` | 包含管理、授权和密钥存储策略，模型调用已在 llm | 管理能力归 platform；不把整个模块迁入 llm。以后若提取配置读取契约，需保持密钥加密规则与现有授权一致 |
| `security_testing/zap/` | 已有独立 protocol、stages、队列 Worker 和持久化服务 | 继续作为安全域子模块。若未来接入第二种扫描器，再评估以 scanners/zap 分组；当前不新增顶层扫描平台 |
| `test_data/runtime/` 与 `providers/` | 生成计划与 Fixture/ProviderExecution 记录、权限和生命周期紧密关联 | 保留在测试数据域；不因名称含 runtime/provider 就迁入通用 execution |
| `web_ui/runtime/` | Playwright 驱动、会话注册、策略和资源释放关联 | 当前保留，浏览器资源继续由 session_manager 唯一持有；有第二个独立使用者时再抽取无领域依赖的浏览器驱动 |
| `reports/`、`dashboard/`、`defects/` | 形成报告、统计和缺陷业务边界，存在必要的跨域事实读取 | 保留各自 feature；不为缩短同级列表将三者合并成巨型 quality 服务 |

静态计数供定位使用：security_testing 约 1.84 万行、test_data 约 0.90 万行、tasks 约 0.59 万行（含各自全部 Python 子模块）。体量不是继续拆分的充分理由；这些模块内部已有多轮职责提取。

## 依赖规则

- `main.py` 负责路由和进程资源装配；不新增第二份独立路由清单。
- 编排层可调用 agents 与业务服务。业务运行时通过公开接口执行，不导入 TaskWorker、任务处理器或任务门面的私有函数。
- 平台与业务确有跨域依赖时通过公开服务或明确的只读契约访问；本轮目录迁移不声称已消除所有依赖环。
- `core/` 保持底座职责，不因目录迁移新增对 platform、orchestration、features 的导入。现存边界问题单独立项处理。
- HTTP、模板解析仍复用现有 execution 实现；领域权限、事务、状态和结果持久化继续归所属业务域。

## 实施顺序

1. 在实际迁移前记录当前源码基线、全部 method/path、OpenAPI schema、模型 metadata、pytest nodeid 和关键动态导入点。HEAD 不能单独代表当前工作区。
2. 将 7 个平台包逐个迁入 platform，更新源码、测试和运行脚本的导入；保持叶子包名。每一批只改变路径归属，不混入权限或服务行为调整。
3. 将 tasks 整包迁入 orchestration。同步更新 main、Agent/Web 调用、工具适配、Alembic 模型发现和测试引用。仅调整 Alembic 环境中的发现路径，不改历史版本迁移脚本或数据库结构。
4. 另一个变更整理任务与 Web 会话绑定的依赖方向。先覆盖权限拒绝、项目归属、运行状态和参与者绑定，再更换调用接口，保留旧入口的保护效果。
5. 更新当前维护中的架构索引和开发说明；历史交付记录保留原路径及其历史语义。

全仓迁移时优先同步修改调用者，不默认建立旧路径转发包。若确有仓库外调用方需要过渡，单独明确兼容期和删除条件，避免同一模型或业务服务从两套实现加载。

## 验收

- 启动导入和 pytest 收集通过；迁移前后 URL、method、Schema 和 ORM 表/字段/约束一致，API 与表名不随 Python 路径变化。
- 全部原有测试保留；每批运行受影响模块的回归，迁移完成后执行完整后端回归。文档中的历史通过数不能代替本次实测结果。
- 验证用户/组织/项目权限、环境选项与敏感配置、任务命令幂等/租约/暂停取消、Web 会话绑定、扫描队列和资源关闭。
- 检查生产代码、测试、脚本及字符串动态导入无遗漏旧路径；Alembic metadata 完整且没有重复实体注册。
- 本轮不改前端接口契约、不增加数据库迁移、不改变事务提交点，不将目录迁移与新功能混合实施。

相关历史：[综合拆分交付](backend-comprehensive-delivery.md)、[Agent 等能力目录重构](08-directory-refactor.md)。这些文档用于理解历史，当前行为以源码和新基线验证为准。
