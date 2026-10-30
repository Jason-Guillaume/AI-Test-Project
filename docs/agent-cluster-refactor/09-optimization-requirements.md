# 可交给 Agent 的目录重构与优化需求

本文定义本轮结构重构的执行范围、阶段产物和验收标准。详细目标架构见 [08 目录重构方案](08-directory-refactor.md)，知识库功能范围见[知识库与业务组装计划](../project-knowledge-business-assembly-plan.md)。本轮 R0–R4 的实测结果、未运行测试与后续事项见[目录重构交付记录](directory-refactor-delivery.md)。

2026-10-28 状态更新：R0–R4 已有代码迁移，公共基础能力的代码已按 C1–C4 归并至 `backend/app/core/`；所选隔离 PostgreSQL 回归已通过，但完整后端 suite 有失败和错误，既有库升级/数据保留验证尚未完成。当前 core 交付与验证边界见 [core 归并交付记录](core-consolidation-delivery.md)；本文件保留 R 阶段实施要求，避免把 core 工作误作尚未完成的能力迁移。

更新日期：2026-10-28。仓库默认位置：`/Users/a1/Desktop/ai-test-project`。下文代码路径均相对仓库根目录；执行环境使用其实际 checkout，不硬编码开发机路径。

## 1. 可直接复制的执行指令

请在当前仓库执行 Agent 共享能力目录重构。先阅读 `docs/agent-cluster-refactor/08-directory-refactor.md`、本文件及 `docs/coding-conventions.md`，核对当前代码、已有改动、真实 Alembic head 和测试入口，然后按 R0–R4 分批完成已有能力迁移。目标是在 `backend/app/` 下独立 `agents/`、`tools/`、`skills/`、`mcp/`，并统一后续知识能力为 `knowledge/`。各包内部按实际功能拆分，业务服务和执行器继续归属原 `features/`。

现有 tasks、治理配置、Skill 文件树、子 Agent 和 MCP 已有实现，请直接迁移复用。默认执行范围为 R0–R4；若当前代码已包含知识库，继续做 R5 迁移并验证。若没有知识库实现，本轮记录 K 阶段待办，不以新增空目录、假检索或只有工具目录项代替实现。新增知识库和业务组装产品功能按独立 K 阶段开发，不作为本轮结构重构的隐含范围。

实现真实注册与调用绑定，保留现有可执行能力范围，不能把 catalog_only 工具升级为模型可调用工具。提取任务模块中的组装、快照、Skill 渲染和 MCP 适配，但保留调度、租约、命令、重试、幂等与回执归属。保留 API、数据库数据、工具 key、运行快照与人工确认行为。不要重做原任务平台或重写测试、安全、Web 执行器。

每阶段完成后运行受影响的验证并记录结果；修复由迁移引入的问题，再继续下一阶段。保留用户已有改动，不为同步分支丢弃工作区。完成后提供路径映射、已完成阶段、实际测试结果、兼容层与剩余限制。不要只提交设计、批量移动文件或声明能力“已接入”。

## 2. 路径与迁移要求

| 当前文件或职责 | 建议目标 | 具体要求 |
|---|---|---|
| `backend/app/features/agent/tools/api_catalog_tool.py` | `backend/app/tools/builtin/api_catalog/` | 查询行为、项目过滤与序列化结果保持 |
| `.../tools/business_tool.py` | `backend/app/tools/builtin/business/` | 继续复用业务公开服务 |
| `.../tools/test_asset_tool.py`、`execution_tool.py` | `backend/app/tools/builtin/test_management/` | 工具 key 不改；执行关联、确认范围及回执不改 |
| `.../tools/fixture_tool.py`、`mock_tool.py` | `backend/app/tools/builtin/test_data/`、`mock_management/` | 复用已有 Fixture/Mock 服务 |
| `.../tools/security_tool.py`、`zap_scan_tool.py` | `backend/app/tools/builtin/security_testing/` | 保留计划确认、风险确认与原扫描执行链 |
| `.../tools/web_ui_tool.py` | `backend/app/tools/builtin/web_ui/` | 保留页面/用例确认和浏览器资源约束 |
| `.../tools/report_tool.py`、`notification_tool.py` | `backend/app/tools/builtin/reports/`、`notifications/` | 保留真实报告来源与通知确认 |
| `backend/app/features/agent_governance/catalog.py` | `backend/app/tools/catalog.py`、`backend/app/agents/workflows/catalog.py` | 分离工具目录与工作流目录，原模块兼容转发 |
| `backend/app/features/agent_governance/models/governance.py` | `backend/app/{agents,skills,mcp,tools}/models/` | 每个模型只有一个真实类定义，表名和数据不变 |
| `backend/app/features/agent_governance/services/governance_service.py` | 各能力的 `services/` | 拆分 Agent、Skill、MCP、工具配置服务，公开入口单向依赖 |
| `backend/app/features/agent_governance/router.py`、`schemas.py` | 兼容聚合路由、分属各能力的 schema | 保留旧 HTTP 路径、字段、状态码和管理员权限 |
| `TaskService._resolve_agent_profile` 等依赖解析 | `backend/app/agents/assembly/` | 返回配置 DTO/快照，由任务服务保存，不反向操作任务状态 |
| `backend/app/features/tasks/runtime/worker.py` 的 `_agent_guidance` | `backend/app/skills/renderer.py` + Agent 上下文组装 | Skill 变量渲染与 Agent 指令组合分开，长度上限和输出行为保持 |
| 同一 Worker 中 MCP schema、函数名和调用适配 | `backend/app/tools/adapters/mcp.py`、`backend/app/mcp/services/` | 调用前复核不移除，任务审计与取消边界不丢失 |
| `backend/app/features/tasks/runtime/subagents.py` | `backend/app/agents/runtime/subagents.py` | 维持原先层级、数量、无工具分析等限制 |
| `backend/app/features/agent/graph.py`、`state.py`、`nodes/` | `backend/app/agents/workflows/legacy/`，后续再分领域 | 先保持图行为迁移；不同时大改状态机 |
| `backend/app/features/agent/{router.py,schemas.py,models/,services/,providers/,prompts/}` | `backend/app/agents/` 对应位置 | 更新导入、提示词资源定位、测试替身与生命周期装配 |
| 执行环境已有知识库实现 | `backend/app/knowledge/` | 同一模块迁移，禁止新建第二份数据库模型/文档库 |

上表 `.../tools/` 均指 `backend/app/features/agent/tools/`。允许按实际文件体量合并小服务，不要求一项职责对应一个空文件。

## 3. 必须满足的实现要求

### OPT-01：职责与依赖

- 对照 08 的依赖规则实施，`tools/skills/mcp/knowledge` 不导入 Agent 图、任务 Worker 或旧治理业务实现。
- 跨业务调用使用公开 `services` 契约；替换本轮触及的私有 `_access` 依赖时，不降低项目鉴权。
- 不向 `core/` 填入领域业务；跨模块公共基础逻辑归 `core/`，模型归属仍留在各能力包。
- 旧路径仅做单向兼容导出，不保留双份模型、工具实现、协议客户端或工作流。

### OPT-02：工具真实可调用且范围不扩张

- 工具元数据和处理器显式关联，运行入口校验工具存在、状态、参数和当前授权。
- 保留工具目录 key、任务调用别名和 MCP 映射；工具详情状态与实际运行保持一致。
- 鉴权上下文、项目、审批与幂等引用由服务端注入，不接受模型覆盖。
- 固定节点可用、目录已登记、允许模型选择应分别表达；人工确认动作不能作为普通模型工具开放。
- 在迁移真实调用点后验证注册路径，不能只增加 registry 而原调用路径全部绕过它。

### OPT-03：Skill 与 Agent 组装

- Skill 定义、修订、ZIP 导入、文件树和变量替换迁入 `skills/`；关联 Agent/任务的使用统计由 Agent 服务聚合，避免 Skill 反向依赖。
- 继续支持数据库 Skill；内置文件与数据库记录有明确装载和版本来源，不自动双写。
- 组装器负责解析模型、Skill、工具、子 Agent 和可选知识范围，返回无凭据的配置结果。
- 保留旧快照 JSON 解释方式，缺少新增可选字段时有兼容默认值；不得静默用最新 Skill 替换历史内容。
- 模型、工具和知识的当前授权继续复核，版本冻结不等于永久授权。

### OPT-04：MCP 与任务控制

- 提取现有协议、发现和调用实现，保留加密凭据、只读审批、停用与撤销校验。
- 任务层继续持有调用前后暂停/取消检查、调用记录、结果不明处理和副作用回执。
- 不扩展为任意 MCP 写工具，不给子 Agent 增加工具权限，不在迁移中引入新传输或框架。

### OPT-05：模型与接口兼容

- 修改 `backend/app/main.py` 的导入和装配时保持原接口，避免重复注册路由或重复启动 Worker。
- 检查 `backend/app/core/models/__init__.py` 的核心基线注册、`backend/app/models/__init__.py` 的历史懒加载映射及 `backend/alembic/env.py` 的模型发现方式，保持核心基线隔离。
- 搜索历史迁移、脚本、测试 fixture 的旧路径依赖；历史迁移文件不修改，必要导入用兼容模块承接。
- 文件移动保持表、外键、索引、key、ID 和历史数据；没有结构变化时不增加 Alembic revision。
- 不改现有框架版本、HTTP 前缀、错误信封、角色模型、Session flag 或业务事务语义。

### OPT-06：知识库与业务组装的归属

- 项目知识管理、版本、受控存储、解析、分块和检索统一归 `backend/app/knowledge/`。
- Agent 知识查询工具归 `backend/app/tools/builtin/knowledge/`，提取与组装图归 `backend/app/agents/workflows/business_assembly/`。
- 草稿、人工编辑、修订、来源字段关联、确定性校验和确认保存归 `backend/app/features/business_assembly/`。
- 正式业务聚合写入留在 `backend/app/features/business/services/`；与草稿保存回执构成有界事务，不能循环调用内部自行 commit 的服务宣称原子保存。
- 若执行环境没有这些能力，仅登记后续阶段、契约与建议路径，不新建空壳或宣称检索和生成已完成。

## 4. 分阶段验收

| 阶段 | 必须提供的证据 |
|---|---|
| R0 | 已实现/未实现清单；当前路径与目标路径映射；实际迁移 head；受影响测试与旧导入依赖 |
| R1 | 旧 Agent 图和任务适配器调用同一工具实现；真实本地工具调用、拒绝调用与稳定 key 验证 |
| R2 | 治理接口的创建/更新/停用/恢复版本、Skill ZIP 与文件树、工具配置、MCP 审批兼容验证 |
| R3 | 新旧快照兼容、Skill 渲染一致、运行中改配置不替换快照、撤权阻止新调用；暂停/取消和重试回执验证 |
| R4 | 旧会话人工暂停与恢复、API/Web/安全/报告相关回归；提示词资源可加载；无循环导入和重复模型 |
| R5（条件） | 知识检索项目隔离、文档版本与来源回链、文档停用/删除与权限撤销后拒绝新访问 |

基础测试入口（使用当前仓库可用运行时，按改动选择，不要求每阶段重复全跑）：

```bash
cd backend
.venv/bin/python -m compileall -q app
.venv/bin/python -m pytest tests/test_16_agent.py tests/test_35_tasks.py tests/test_36_agent_governance_details.py -q
.venv/bin/python -m pytest tests/test_32_zap_agent_approval.py tests/test_33_web_agent_loop.py tests/test_task_notifications.py -q
```

按实际改动补充 `test_32_web_agent_runtime.py`、`test_34_web_agent_console.py` 等验证。复用现有行为测试；仅为迁移引入的真实风险增加工具注册、导入边界、快照兼容或 MCP 撤权测试，不为每个转发文件写重复测试。

模型归属迁移还必须在隔离环境分别验证全新进程的空库迁移和现有库升级，检查基线表与后续表不冲突、数据保留、同表只有一份 ORM 定义。不要在开发者现有库执行清库验证；不能把当前文档里的 `0029` 当作未来固定 head。

若 HTTP 行为和前端代码均未变，不做无关前端重构；接口契约必须保持，若实际触及前端则运行其现有检查。没有执行的测试、缺失环境和外部集成限制如实记录，不能以编译通过替代运行验证。

## 5. 知识库后续建议需求（K 阶段）

以下是建议的独立功能任务，当前结构重构不自动承担：

| 阶段 | 功能与建议路径 | 验收场景 |
|---|---|---|
| K1：知识接入与检索 | `backend/app/knowledge/`；`frontend/src/pages/console/Knowledge/`；`frontend/src/api/knowledge.ts` | 项目内上传 Markdown/TXT/DOCX/文本 PDF，异步解析、保留可用旧版本、按关键词/章节检索并定位来源；新依赖先核对兼容性 |
| K2：知识驱动业务草稿 | `backend/app/agents/workflows/business_assembly/`；`backend/app/tools/builtin/{knowledge,business_assembly}/`；`backend/app/features/business_assembly/` | `BUSINESS_ASSEMBLY` 不要求测试环境；固定文档版本、按章节提取、记录覆盖；生成有依据、可编辑、有缺失提示的草稿 |
| K3：人工编辑与保存 | `backend/app/features/business_assembly/services/`；`backend/app/features/business/services/`；`frontend/src/pages/console/BusinessManagement/` | 校验指定修订、冲突提示、确认保存为正式业务 DRAFT；事务内保存回执与 ID 映射，重复确认不重复创建，无测试/扫描/通知副作用 |

字段、接口、删除保留策略和产品验收以知识计划为准；这些前端路径是建议新增位置，不表示页面已存在。不默认加入 OCR、向量数据库、复杂分支执行或自动覆盖已有业务。

## 6. 交付与完成标准

在 `docs/agent-cluster-refactor/directory-refactor-delivery.md` 新增实施记录，包含：实际代码基线、完成的 R 阶段、路径映射、保留的兼容导出及原因、HTTP/快照兼容情况、迁移与测试命令和结果、剩余 K 阶段和已知限制。实际交付记录见[目录重构交付记录](directory-refactor-delivery.md)，其中仅列本轮实测结果。

同步更新 `docs/coding-conventions.md`、`docs/agent-governance-runtime.md`、本目录索引及本次实际受影响的设计路径。当前目录规范只在代码迁移落地时更新，不把设计图写成已实现现状。

完成意味着现有调用已切换到唯一的新实现、行为验收通过、历史任务和接口可兼容读取；仅移动文件、保留新旧双份实现、让测试跳过或隐藏失败不算完成。回退优先恢复导入和路由装配，保留现有数据；引入新结构的 K 阶段另行按知识计划验证迁移与回滚。
