# 任务与智能体集群重构文档

2026-10-30 前端整单入口：[23 前端全量审查](23-frontend-full-audit.md)、[24 前端重构与后端收尾计划](24-frontend-comprehensive-refactor-plan.md)、[25 Agent 提示词](25-frontend-comprehensive-agent-prompt.md)、[U0–U12 连续实施进度](frontend-comprehensive-progress.md)、[实施交付/验收/回退](frontend-comprehensive-delivery.md)。静态证据、原始迁移建议和本次实际迁移账本分别保留审查时点与实施结果。

2026-10-29 的 [22 后端全模块审查与实施清单](22-backend-capability-audit.md) 和 [21 Web/Mock 专题](21-capability-boundaries-and-naming-plan.md) 保留审查时点；其后整改结果与有意保留边界见[后端能力边界整改交付记录](backend-capability-refactor-delivery.md)，不能仅按旧计划推断当前源码未整改。

本目录定义测试平台向“全局助手 + 每任务独立智能体团队”演进的产品需求、架构、协作、前端、实施与验收要求，供实施智能体和开发者共同使用。管理页面及现有业务数据模型继续保留。

编制日期：2026-10-26。01–07 的 P0–P6 产品方案仍按阶段实施；共享能力目录 R0–R4 代码迁移已实施；数据库行为验收受隔离测试库凭据限制，实测范围见[目录重构交付记录](directory-refactor-delivery.md)。本文档包不是功能交付报告；端点、实体和页面除明确标记为现状者外，仍属产品设计。

P0–P6 产品阶段记录见[实施交付记录](delivery-record.md)；共享能力目录 R0–R4 的代码迁移与实测见[目录重构交付记录](directory-refactor-delivery.md)。两份记录与设计基线分开维护。

2026-10-28 补充：现有任务、治理配置、Skill 与 MCP 已有实现，01–07 保留原始产品与运行设计，不代表今天仍需从零建设。当前目录重构以 [08 目录重构方案](08-directory-refactor.md) 为准；给下一位 Agent 的执行入口是 [09 优化需求](09-optimization-requirements.md)。知识库一并纳入目标结构，实际完成情况仍以代码和测试为准。

公共底座 models/shared 已按 [10 core 归并计划](10-core-consolidation-plan.md) 落到 `backend/app/core/`；随后已删除只做旧路径转发的兼容文件，当前代码统一使用规范路径。[core 归并交付记录](core-consolidation-delivery.md)保留归并当时的验证事实，并补充后续清理记录。[11 执行提示词](11-core-consolidation-agent-prompt.md)中的保留旧入口要求已被本次清理覆盖。

任务模块 T0–T3 已按 [12 拆分计划](12-task-module-split-plan.md) 与 [13 需求提示词](13-task-module-split-agent-prompt.md) 实施；统一任务前端已完成首轮页面拆分。实际路径、`TaskService`/`TaskWorker` 方法兼容入口、事务边界及前后端验证结果见[任务模块拆分交付记录](task-module-split-delivery.md)。旧导入路径纯转发文件已清理。当时 T4–T6 运行控制尚未拆分，现已纳入下述 B0–B9；其他前端页面拆分不在本单。

2026-10-29 兼容文件清理：`app.shared`、`app.models`、旧 `features.agent`/治理转发模块、各 Feature 的 `_access.py` 转发文件，以及前端 Agent、Mock、Reports、Tasks、TestManagement 页面纯 re-export 入口均已删除；调用方已迁移到规范模块或页面文件。包含实际 HTTP 处理逻辑的 `features/agent_governance/router.py`、真实 ZAP access 服务和 TaskService/TaskWorker 对外方法保留。具体清单见[任务模块拆分交付记录](task-module-split-delivery.md)。

2026-10-29 业务共享能力 E0–E4 已实施：HTTP 执行与模板解析归 `app/execution/`，路径/比较原语归 `app/core/expressions/`，模型调用与追踪归 `app/llm/`；领域授权、语义和业务结论仍由原模块持有。真实路径、测试结果和限制见[业务能力提取交付记录](business-capability-extraction-delivery.md)。E5 仅记录契约建议，尚未开发或注册工具。

2026-10-29 已按 [16 修复与目录优化计划](16-backend-stabilization-and-split-plan.md) 和 [17 需求提示词](17-backend-stabilization-agent-prompt.md) 完成 F0–F4：ZAP 装配、治理协调、HTTP 边界、测试导入与误收集修复；最终后端全量回归 1042 passed、47 warnings。逐项基线、nodeid 差异、浏览器登录超时定位和回退步骤见[稳定化交付记录](backend-stabilization-delivery.md)。F 阶段当时未实施 D1–D4，后续现已统一纳入 B0–B9。

2026-10-29 用户要求合并后续实施范围：以 [18 后端综合工作包](18-backend-comprehensive-refactor-plan.md) 与 [19 总需求提示词](19-backend-comprehensive-agent-prompt.md) 一次委托 B0–B9，覆盖 D1–D4、T4–T6 及相关领域整理。内部检查点自动推进，不再要求用户逐小阶段重新下任务。后续实际实施与验证统一见[综合交付记录](backend-comprehensive-delivery.md)，执行过程见[进度记录](backend-comprehensive-progress.md)。

2026-10-29 features 目录归属已实施：七个管理平台模块迁到 `app/platform/`，tasks 迁到 `app/orchestration/tasks/`，十个业务模块留在 `app/features/`。Web UI 不再反向导入任务 ORM；任务编排通过窄绑定校验回调保持运行、环境、项目和 UI Worker 校验。迁移基线、实际映射和实测限制见[features 目录迁移基线](features-layout-baseline.md)及[features 目录迁移交付记录](features-directory-layout-delivery.md)。


2026-10-30 后端能力边界与命名整改已实施，实际路径、C01–C12 取舍、Web/Mock 专题、事务边界及实测回归见[后端能力边界整改交付记录](backend-capability-refactor-delivery.md)。方案文档仍保留审查时点，不作为完成证据。

## 文档与建议阅读顺序

| 文档 | 内容 | 主要用途 |
|---|---|---|
| [23 前端全量审查](23-frontend-full-audit.md) | 全部源码静态清单、当前问题、大文件职责、前端实测与后端现状 | 当前前端优化事实依据 |
| [24 前端整单重构计划](24-frontend-comprehensive-refactor-plan.md) | 五层目录、全模块归属、U0–U12、后端收尾、工作量和验收 | 一次委托完成综合优化 |
| [25 前端整单提示词](25-frontend-comprehensive-agent-prompt.md) | 完整绝对路径、连续实施范围和交付约束 | 复制给实施 Agent |
| [前端整单进度](frontend-comprehensive-progress.md) | U0–U12 检查点、已完成工作与当前验证阻塞 | 连续推进状态 |
| [前端整单交付](frontend-comprehensive-delivery.md) | 实际迁移清单、验证结果、未完成项和回退说明 | 复核本次实施 |
| [01 产品需求与范围](01-requirements.md) | 目标、概念、职责、文件能力、初始决定 | 确认做什么、保留什么 |
| [02 后端架构与运行机制](02-architecture.md) | 现状依据、模块、数据、调度、权限、API | 设计后端与运行底座 |
| [03 任务内智能体协作协议](03-collaboration-protocol.md) | 角色交接、消息路由、方案变更、业务衔接 | 实现真正的多角色协作 |
| [04 前端页面与交互设计](04-frontend-design.md) | 任务列表、参与者会话、全局抽屉、配置中心 | 实现任务与管理页共存 |
| [05 分阶段实施计划](05-implementation-plan.md) | P0–P6、交付依赖、阶段验收与拆分 | 控制实施范围和顺序 |
| [06 验收、迁移与回滚](06-validation-and-migration.md) | 测试、恢复、兼容、灰度与回滚 | 判断是否真正交付 |
| [07 实施交接指令](07-agent-handoff.md) | 可复制给实施智能体的完整要求 | 启动重构工作 |
| [08 共享能力目录重构](08-directory-refactor.md) | agents / tools / skills / mcp / knowledge 的目标路径、职责、依赖与兼容 | 本轮目录重构设计基线 |
| [09 Agent 优化需求](09-optimization-requirements.md) | 可复制执行指令、路径映射、R0–R5 验收和 K 阶段建议需求 | 当前结构重构范围与标准 |
| [10 core 归并计划](10-core-consolidation-plan.md) | models/shared 的目标归属、C0–C5、兼容、迁移与验证 | 下一轮公共底座优化方案 |
| [11 core 执行提示词](11-core-consolidation-agent-prompt.md) | 可复制的实施要求与绝对文件路径 | 交给 Agent 实施 core 归并 |
| [12 任务模块拆分计划](12-task-module-split-plan.md) | T0–T3 首批范围、T4–T6 后续方向、方法映射和事务/回归要求 | 下一轮任务模块优化基线 |
| [13 任务模块需求提示词](13-task-module-split-agent-prompt.md) | 可复制执行要求、文件路径与完成标准 | 交给 Agent 实施 T0–T3 |
| [14 业务共享能力提取计划](14-business-capability-extraction-plan.md) | HTTP/表达式/LLM/模板的归属、语义、E0–E4 验收和 E5 工具建议 | 下一轮跨业务域能力提取基线 |
| [15 业务能力需求提示词](15-business-capability-agent-prompt.md) | 可复制实施要求、文件路径与完成标准 | 交给 Agent 实施 E0–E4 |
| [16 后端修复与目录优化计划](16-backend-stabilization-and-split-plan.md) | 已核查问题、F0–F4、逐项回归门槛和 D1–D4 后续路线 | 当前后端稳定化实施基线 |
| [17 后端修复需求提示词](17-backend-stabilization-agent-prompt.md) | 可复制执行要求、文件路径与交付标准 | 交给 Agent 实施 F0–F4 |
| [18 后端综合拆分工作包](18-backend-comprehensive-refactor-plan.md) | B0–B9 完整范围、路径、工作量、依赖与统一验收 | 一次委托后端主要领域拆分 |
| [19 后端综合总提示词](19-backend-comprehensive-agent-prompt.md) | 自动推进所有工作包的总需求与持续交付规则 | 交给 Agent 连续完成整单 |
| [20 features 目录布局方案](20-features-directory-layout-plan.md) | 7 个平台模块、tasks 和 10 个业务模块的归属及验收要求 | 本次目录调整设计依据 |
| [features 目录迁移基线](features-layout-baseline.md) | 迁移前工作区、API、ORM 和 pytest 收集基线 | 对照本次迁移验证 |
| [features 目录迁移交付记录](features-directory-layout-delivery.md) | 真实路径映射、依赖调整、测试结果与未完成验证 | 本次目录调整交付证据 |
| [后端综合交付（B0–B9）](backend-comprehensive-delivery.md) | 全包真实目录、生产调用、事务、契约、逐项测试与回退 | 当前后端职责拆分交付入口 |
| [业务能力提取交付记录](business-capability-extraction-delivery.md) | E0–E4 实际路径、语义承接、测试结果、未完成项与回退方式 | 本轮实际交付证据 |
| [后端能力边界整改交付记录](backend-capability-refactor-delivery.md) | C01–C12、Web/Mock 迁移映射、事务约束与本次完整验证 | 当前能力边界整改证据 |
| [目录重构交付记录](directory-refactor-delivery.md) | R0–R4 实际迁移路径、验证结果、兼容入口与未完成事项 | 本轮实际交付证据 |
| [core 归并交付记录](core-consolidation-delivery.md) | C0–C5 实际路径、历史旧导入入口及后续删除记录、验证结果与未完成事项 | 公共底座归并证据 |

实施前还应读取仓库的 [编码规范](../coding-conventions.md) 和 [项目开发指引](../../.claude/skills/develop-this-project/SKILL.md)。项目事实以当前代码为准；核对差异后同步修正文档，不照搬过期版本号或端点。

## 首个可用版本

先完成 P0–P3：任务运行底座、主 Agent / Planner / API Worker / 报告 Agent，以及任务列表、独立会话、全局抽屉与业务产物回链。随后按 P4–P6 接入 UI、安全测试、审阅返工、自定义配置、文件扩展和灰度迁移。

每个任务的角色实例独立保存上下文、状态和消息。运行中 Worker 的角色与状态来自真实执行记录，不能仅在 UI 中增加几个角色名称。

## 需求追踪

| 核心要求 | 设计文档 | 实施与验收 |
|---|---|---|
| 原有管理页面和业务数据保留 | 01、03、04 | P3、P6；06 兼容测试 |
| 每任务独立的多职责智能体 | 01、02、03 | P2、P4；06 隔离与协作测试 |
| 右侧全局调度抽屉 | 03、04 | P3；06 路由/项目切换测试 |
| 持久化调度、暂停、取消、重试 | 02、03 | P1；06 故障与幂等测试 |
| Agent / Skill / Tool / LLM 配置 | 01、02、04 | P2 基础绑定，P5 配置中心；06 版本测试 |
| 文件输入与证据引用 | 01、02、03 | P2 基础文本，P5 格式扩展；06 权限与引用测试 |

## 文档维护规则

- 保持概念一致：Task 是统一工作任务；TaskRun 是其运行；TestPlan / TestRun 仍是原有测试业务对象。
- 产品范围以 01 为准，角色协作以 03 为准，状态与数据一致性以 02 为准，交付顺序以 05 为准，完成标准以 06 为准。
- 对跨文档存在冲突的内容，实施前明确解决并同步修改；不能默默选择容易实现的部分而遗漏验收项。
- 每阶段交付记录新增或更新到本目录，列出已实现、实际测试结果、未实现和已知限制，不把计划当成交付证据。
- 目录与能力归属使用 08；本轮结构重构范围和完成标准使用 09。知识库功能范围使用[项目知识库与业务组装计划](../project-knowledge-business-assembly-plan.md)，不将其尚未实现的功能列为现有能力。
- models/shared 的实际归并按 10 与 core 交付记录核对；兼容模块删除状态按后续清理记录核对，既有 R 阶段文档保留为历史事实。
- tasks 下一轮拆分按 12/13 执行；T0 先复核既有失败，交付记录区分基线失败、新增失败及未测项，不提前把完整目标目录标记为已实现。
- 业务共享能力 E0–E4 的现状以交付记录为准；后续 E5 工具需独立实施并验证真实服务、权限、无副作用和脱敏边界，不恢复已清理的兼容目录，也不把契约建议标记成已接入能力。
- 后续稳定化按 16/17 执行，失败来源以逐项证据判断；F 阶段修复和 D 阶段目录优化分别交付，不以专项测试通过替代全量行为验收。
- 用户已将后续拆分合并为 18/19 的整单 B0–B9；该范围覆盖旧文档的逐小阶段实施限制，执行者内部验证后连续推进，保留 1042 项基线及实际交付证据。
