# 后端能力边界与命名整改交付记录

日期：2026-10-30。依据 [22 后端全模块审查与实施清单](22-backend-capability-audit.md)、[21 Web/Mock 专题方案](21-capability-boundaries-and-naming-plan.md) 和审查证据实施。实施前工作区已有大量未提交变更；本次未重置、清理或覆盖其无关内容。

## 基线与范围

- 2026-10-29 整改前后端基线：1062/1062 通过，47 warnings，367.76 秒；本次以该结果作为前态参照，不以它替代当前回归。
- 整改前后 pytest 收集均为 1062 个 nodeid，集合差异：删除 0、新增 0。测试源码中的路径更新没有移除、跳过或放宽用例。
- 本次没有新增数据库迁移或修改历史迁移脚本。Alembic 环境与迁移文件哈希相对本次实施基线一致。
- 本次记录中的 API、工具 key、权限和事务结论以当前代码与本次行为测试为准；`22`、`21` 和旧交付报告保留审查/交付当时语义，静态证据 JSON 未改写。

## 迁移映射与职责

| 原实现/路径 | 当前实现/路径 | 职责与兼容说明 |
|---|---|---|
| 七处项目读取/写权限副本及跨域借用测试权限 helper | `platform/projects/services/access_service.py` | 项目可见性与普通写入唯一契约；领域实体到项目 ID 的解析及高风险额外门槛仍归各业务域。保持 404/403 语义。 |
| `platform/organizations/router.py` 中的组织、成员、负责人和授权事务 | `platform/organizations/services/management_service.py` | Router 保留既有 URL、方法和响应契约；组织/Owner 原子提交及模型授权语义在服务中。 |
| 通知收件箱路由中的可见范围、标读、删除和提交 | `platform/notifications/services/inbox_service.py` | 收件箱服务持有业务查询与原 commit 点；事件读取仍留薄路由。 |
| 飞书服务中的报告规则、卡片和投递协调 | `orchestration/report_delivery/{card_builder,service}.py` 与 `platform/notifications/services/feishu_service.py` | 报告投递用例统一供 HTTP 与 Agent 工具调用；通用渠道发送只接收卡片数据，发送失败仍不改变报告/TestRun。 |
| 任务处理器内的 Planner、Worker、Reviewer、Main 提示词和模型候选调用 | `agents/services/task_decision_service.py` | Agent 服务只接收冻结配置、提示词、受限候选输入和 Provider；不接收 `TaskRun`，不写任务状态。MCP 回调、任务锁、事件、审批、回执及事务仍由任务编排持有。 |
| `tools/builtin/test_management/execution_tool.py` 内临时计划/套件/运行写入，任务借用工具入口 | `features/test_management/services/selected_case_run_service.py` | 工具与任务编排分别调用公开业务服务；保留原计划/套件/关联/运行提交与回执顺序。 |
| Mock 工具中的 Agent 安全查询与字段投影 | `features/mocking/services/agent_catalog_service.py` | 统一项目校验、白名单字段、响应结构脱敏和按需查询；工具保留原 key 与授权。 |
| Web Agent 节点通过 HTTP router 单例、直接读取/锁任务 ORM | `agents/workflows/legacy/nodes/web_agent.py` + `orchestration/tasks/services/web_authoring_service.py` | Agent 不导入 Web HTTP Router 或 TaskRun；任务协调器注入动作执行回调，在浏览器动作前锁定 TaskRun，控制检查及提案/步骤回执提交继续由原服务串行完成。 |
| `features/web_ui/` | `features/web_testing/` | 正式 Web 测试资产、权限、确认指纹、执行记录及 TestRun 适配。公开 API 路径、Schema 和数据库表名保持不变。 |
| `features/mock_management/` | `features/mocking/` | Mock 管理、匹配、上下文、响应、运行和执行留痕全部仍由 Mock 业务域拥有。运行入口仍使用既有 X-Mock-Token/public_runtime 规则。 |
| `tools/builtin/{web_ui,mock_management}/` | `tools/builtin/{web_testing,mocking}/` | 仅 Python 包路径改名；`web_ui.generate_draft`、`runtime.mock_management.*` 等外部工具 key、风险和授权不变。 |
| WebAgentSession/WebAgentStep 原 Web 模型文件 | 唯一类定义 `agents/models/browser_authoring.py`；Web 模型包仅重导出类 | 原表名、列、外键和唯一 metadata 定义不变；探索会话 ORM 不复制。 |
| Web 探索会话 lifecycle 与正式资产提升混合 | `agents/browser_authoring/services/session_service.py` 与 `features/web_testing/services/promotion_service.py` | 会话启动、读取、观察、步骤留痕和关闭归 Agent 编写；已接受步骤提升成正式但未确认的用例归 Web 测试。 |
| Web/Agent/业务共享的 Playwright 驱动、观察器、Registry | 唯一实现 `execution/browser/` | `BrowserSession`、`SessionRegistry`、`PlaywrightExecutor`、`TargetPolicy` 均只有一份实现；保留 owner 线程、两槽并发、回收和进程退出清理。 |
| 浏览器策略内部查询 ProjectOutboundTarget | Web 服务侧 `services/target_policy_service.py` 构造已授权快照并注入 `execution/browser/policy.py` | Runtime 不查询 ORM、不接收模型提供的授权目标；DNS 冻结、精确目标匹配、重定向拦截保持。 |
| Browser Registry 在运行时直接写 WebAgentSession | Web 服务 `runtime_lifecycle_service.py` 回调 | 运行时只负责关浏览器资源，Web 服务仍以原提交行为持久化过期状态。 |
| Web API/业务适配器依赖浏览器驱动模块 | `features/web_testing/services/execution_adapter.py` 与 `core/security/sanitizer.py::mask_known_secrets` | 正式执行适配留在 Web 域；业务执行结果脱敏不再导入 Playwright 驱动。 |
| Mock HTTP Router 在线程池函数直接 commit | `MockRuntimeService.handle_runtime_request()` | Router 只采集请求、在线程池调用服务及应用延迟；内部 `handle_request()` 继续 flush-only。执行记录仍先于模拟延迟/超时提交。 |

## C01–C12 逐项结果

| 项目 | 结果 | 说明 |
|---|---|---|
| C01 项目访问权限重复 | 完成 | 通用项目访问/普通写权限只在 platform 项目服务定义；实体归属解析和额外策略保留在业务域。 |
| C02 组织管理事务留在 Router | 完成 | 管理用例迁入组织服务，原有组织成员与 Owner 事务顺序及限制保持。 |
| C03 通知收件箱、渠道、报告投递混合 | 完成 | Inbox、通用渠道传输、报告投递协调分层；HTTP 与工具共用投递服务。 |
| C04 任务处理器承担 Agent 决策 | 完成 | 角色 prompt、结构化候选和文本候选调用归 Agent 决策服务；Planner 的 MCP 事务回调仍由任务层控制。 |
| C05 Agent/任务反向依赖 | 优先项完成，统计子项后续 | Web 动作许可、TaskRun 刷新/行锁和回执在编排协调器；Web Agent 节点不读任务 ORM。`agents/services/reference_service.py` 的 Skill 使用统计仍只读联查 TaskRun，依方案列为低风险后续治理查询，不影响调度。 |
| C06 工具拥有领域写入/任务借工具实现 | 重点整改完成 | 选定用例创建与执行回归 test_management 公开服务，任务和工具分别调用；Mock Agent-safe 查询回归 Mock 服务。其他内置业务工具保留必要的只读投影/资产上下文读取，没有把 ORM 导入一概当作错误；工具目录覆写仍由 `tools/services/tool_service.py` 在调用方事务内维护，不由内置业务适配器提交。 |
| C07 业务与 Web/测试关联方向 | 完成 | Web 绑定执行经 `run_web_binding` / `run_web_case` 服务契约；Web 目标/确认仍由 Web 适配器复核。Business Binding 对 WebCase 的只读存在性检查作为绑定失效判定保留，不复制实体。 |
| C08 测试执行与安全执行注册分派 | 后续，未实施 | 当前延迟导入关系可运行；没有实际扩展需求。抽取注册器会触及安全优先顺序、普通用例回退与结果生命周期，收益低于风险，本轮保留现状。 |
| C09 TestCaseMock 配置归属和 Mock Router 提交 | 部分完成 | HTTP 请求完整用例的 commit 已迁入 Mock 服务，内部 `handle_request` 仍 flush-only。`TestCaseMock` 声明服务暂留 Mocking：其校验对象是同一 Mock 场景/service/endpoint/scope，移动到 Test Management 的收益有限且会扩大当前 Mock API/工具事务改动面；相关约束测试保留。 |
| C10 看板 readiness 运维职责 | 后续，未实施 | readiness 仅为现有只读检查，当前无单独运维能力维护需求；不为目录拆分建立空的 operations 包。 |
| C11 模型密文派生重复 | 后续，未实施 | 模型 API Key 包装存在 strip/空值/静默失败行为，通用密文包含原文与告警策略。当前合并收益不足以抵消密文兼容风险。 |
| C12 基础执行层调用公开平台配置契约 | 保留 | HTTP 出站授权和 Provider 模型配置读取仍使用公开查询契约；没有为追求零跨包导入增加转发层。 |

可选/后续项目的状态是有意保留，不标记为已实施或已验证；维护时应在确有扩展需求时独立立项。

## Web/Mock 专题验收状态

- Web 正式业务路径、探索会话服务、模型候选生成及浏览器技术运行时各有明确归属。`web_testing.schemas` 继续导出原 Pydantic 类型；浏览器步骤、Locator、Upload 的校验实现唯一。人工确认、逐步提案审批、任务暂停/取消边界、会话线程/配额/回收、清理链均保留。
- Mock 完整管理与运行能力继续属于 `features/mocking/`；Agent 工具只暴露原受控只读查询，既有工具 key 和授权不变。Mock Token 与平台 JWT 执行面继续分离，运行上下文仍按项目校验。
- 没有新增 ORM 映射、重复 Browser Registry、第二执行链或空壳 package；没有新增迁移。

## 实测验证

整改前基线（用于收集和对照，不替代本次结果）：**1062 passed / 47 warnings / 367.76 秒**。

本次影响面回归：

| 范围 | 实测 |
|---|---:|
| 认证/隔离/持久化、通知与报告（此前分批） | 61 passed / 16 warnings |
| Web/Agent/任务控制与 Mock（修正测试夹具后独立重跑） | 相关首批 83 passed；2 条项目夹具引用错误修正后 2 passed |
| C04 任务决策、任务消息/审阅与治理快照 | 36 passed / 13 warnings |
| 业务执行/集成、测试执行、Mock、Web 浏览器/Agent、任务 Web 绑定 | 167 passed / 16 warnings |
| Agent 草稿仍需人工确认（候选生成迁移后） | 1 passed / 11 warnings |
| pytest nodeid 集合比较 | 整改前 1062，整改后 1062；新增 0、删除 0 |
| 应用与后端 Python 编译检查 | 通过 |
| 迁移文件哈希对照 | 相对本次基线无变化 |
| 完整后端回归（最终源码） | **1062 passed / 47 warnings / 352.95 秒** |

全量回归使用隔离 PostgreSQL `127.0.0.1:55439` 对应的专用测试容器；退出码为 0。47 项 warning 与整改前基线计数一致。测试输出仍包含既有依赖弃用提示、Pydantic 字段名提示、ORM 类误收集提示、短测试 JWT 密钥提示、一个测试数据 SQLAlchemy 提示及 Mock catch-all 多 HTTP 方法的 OpenAPI operationId 提示；本次未通过跳过或过滤来隐藏它们。

## 未完成项与维护边界

C05 的 Skill 使用治理统计、C08、C10、C11 未实施；C09 的 TestCaseMock 服务归属仍保留。其他工具内的只读资产投影没有统一抽成空壳服务。业务绑定对 Web 用例身份的只读联查仍保留在业务绑定规则中，正式执行走 Web 服务契约。
