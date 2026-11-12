# Agent、Tool、Skill、MCP 与知识库目录重构方案

本文定义共享能力的目标目录、依赖边界和迁移顺序；R0–R4 的实际代码迁移与验证结果见[目录重构交付记录](directory-refactor-delivery.md)。本轮未发现知识库实现，因此没有创建 `knowledge/` 空壳；K1–K3 仍是独立后续开发。

更新日期：2026-10-28。核对基线：当前工作区，HEAD 为 `e46cbc9`；包含已有本地改动，不能将该提交号视为全部已核对文件的版本。实施时重新核对执行环境的代码和迁移 head。

[返回索引](README.md) · [可交给 Agent 的优化需求](09-optimization-requirements.md) · [知识库与业务组装计划](../project-knowledge-business-assembly-plan.md)

> 2026-10-28 状态更新：models/shared 的代码已按 C1–C4 归并到 `backend/app/core/`；隔离 PostgreSQL 回归已运行，所选核心用例通过，但全量后端 suite 仍有失败和错误，既有库升级及数据保留尚未验证。此后 `app.models`、`app.shared` 以及旧 Agent 路径的纯转发文件已删除，当前导入使用规范模块。实际路径、验证结果与未完成项见 [core 归并交付记录](core-consolidation-delivery.md)。本文 R0–R4 的 Agent/Tool/Skill/MCP 迁移记录继续有效。

## 1. 目标与现状

目标是在 `backend/app/` 下独立 `agents/`、`tools/`、`skills/`、`mcp/`、`knowledge/`，内部按实际功能划分；业务服务、数据和执行器继续归属 `features/`。使用复数 Python 包名 `agents`、`tools`、`skills`，MCP 包统一小写 `mcp`。

| 已核对位置（迁移前基线） | 当时职责 | 已完成迁移方向 |
|---|---|---|
| `backend/app/features/agent/` | 会话、图、节点、提示词、模型调用、工具 | Agent 本体归 `app/agents/`，工具归 `app/tools/` |
| `backend/app/features/agent_governance/` | Agent、Skill、MCP、工具配置及目录 | 按能力拆分实现，治理页面和既有接口暂保留聚合入口 |
| `backend/app/features/tasks/services/task_service.py` | 任务管理、Agent 依赖解析、运行快照 | 提取能力解析与配置快照，任务状态和持久化仍留任务服务 |
| `backend/app/features/tasks/runtime/worker.py` | 调度、角色运行、Skill 渲染、MCP 调用适配 | 提取可复用组装与运行逻辑，保留领取、控制命令、租约及回执 |
| `backend/app/features/tasks/runtime/subagents.py` | 子 Agent 分析图 | 迁入 `app/agents/runtime/`，保留当前工具与层级限制 |
| `backend/app/core/models/__init__.py`、`backend/app/models/__init__.py` | 核心模型注册、旧路径与历史名称懒加载 | 保持九张核心基线隔离，旧名称转发至唯一实体 |
| `docs/project-knowledge-business-assembly-plan.md` | 知识库与业务组装规划 | 纳入目标结构；当前定位范围尚未发现相应实现 |

本轮实测 Alembic head 为 `0029_agent_tool_overrides`。任务、治理配置、Skill 文件树和 MCP 已有实现，不能按旧文档重新建设；验证限制见交付记录。

## 2. 目标目录

下列是职责清单，实施时只创建有实现的文件。现有接口可暂由兼容路由提供，不要求同一阶段补齐所有独立 router。

```text
backend/app/
├── main.py                          # 唯一 HTTP 路由和生命周期装配入口
├── agents/
│   ├── models/                      # Agent 定义、修订、会话与消息
│   ├── schemas.py
│   ├── services/                    # 定义管理、会话服务的公开入口
│   ├── assembly/
│   │   ├── builder.py               # 解析工作流、模型、Skill、工具与知识范围
│   │   └── snapshot.py              # 创建不含凭据的运行配置快照
│   ├── runtime/
│   │   ├── context.py               # 受信任的调用身份与运行上下文
│   │   └── subagents.py
│   ├── workflows/
│   │   ├── catalog.py               # 工作流模板元数据
│   │   ├── legacy/                  # 首先原样迁移现有 graph/state/nodes
│   │   ├── api_testing/             # 后续按职责提取，实际使用时再创建
│   │   ├── web_testing/
│   │   ├── security_testing/
│   │   ├── reporting/
│   │   └── business_assembly/       # 新知识组装工作流，后续阶段实现
│   ├── providers/                   # 保留现有模型调用、追踪、脱敏实现
│   └── prompts/                     # 工作流内部提示词
├── tools/
│   ├── contracts.py                 # 工具规格和调用上下文契约
│   ├── registry.py                  # 注册、能力查询与执行处理器绑定
│   ├── dispatcher.py                # 授权检查和受控调用入口
│   ├── catalog.py                   # 现有工具 key、目录与运行状态说明
│   ├── models/                      # ToolDefinitionOverride
│   ├── services/                    # 工具配置管理
│   ├── adapters/mcp.py              # MCP 工具到统一工具契约的适配
│   └── builtin/
│       ├── api_catalog/
│       ├── business/
│       ├── test_management/         # 测试资产及用例执行工具
│       ├── test_data/               # fixture_tool
│       ├── mock_management/
│       ├── web_ui/
│       ├── security_testing/        # security_tool、zap_scan_tool
│       ├── reports/
│       ├── notifications/
│       ├── knowledge/               # 后续知识检索工具
│       └── business_assembly/       # 后续草稿工具
├── skills/
│   ├── models/                      # 定义、修订、使用事件
│   ├── schemas.py
│   ├── services/                    # 管理、版本与 ZIP 导入；使用统计由 Agent 层聚合
│   ├── loader.py                    # 统一加载内容与附属文件
│   ├── renderer.py                  # 变量替换、上下文渲染和长度限制
│   └── builtin/<scenario>/SKILL.md   # 需要随代码发布时才增加
├── mcp/
│   ├── models/                      # MCPServer
│   ├── schemas.py
│   ├── services/                    # 服务管理、发现、审批和调用复核
│   ├── client.py                    # 当前 MCP 协议实现
│   └── transports/                  # 实际存在多种传输时再拆分
├── knowledge/                       # 后续知识库能力，已存在则直接迁入
│   ├── router.py
│   ├── schemas.py
│   ├── models/                      # 库、文档、版本、分块、解析作业
│   ├── services/                    # 管理、接入协调、检索与来源读取
│   ├── parsers/                     # 文档格式解析
│   ├── processing/                  # 分块与索引构建
│   ├── retrieval/                   # 检索契约及 PostgreSQL 实现
│   ├── storage/                     # 受控文件存储适配
│   └── runtime/parse_worker.py      # 持久化解析作业处理
├── features/
│   ├── tasks/                       # 调度、命令、状态、租约、事件、回执
│   ├── agent_governance/            # 兼容 HTTP 聚合，逐步移除旧业务实现
│   ├── business_assembly/           # 后续业务草稿、修订、校验及保存协调
│   ├── business/                    # 正式业务数据及聚合写入服务
│   └── ...                          # 其余领域服务与执行器保持归属
├── core/                            # 配置、数据库基类、核心模型、安全、HTTP 与通知写入
│   ├── database/                    # Base 独立于 engine/session
│   ├── models/                      # 九张平台核心基线表
│   ├── security/                    # 认证、角色、加密、密码与脱敏
│   ├── http/                        # 依赖、错误、分页、限流与请求上下文
│   └── notifications/               # 通知写库
├── shared/                          # 指向 core 的旧路径兼容模块
└── models/                          # 核心模型旧路径及历史名称懒加载兼容
```

`legacy/` 是迁移过渡位置，不重写已有图的边、状态字段或暂停点。后续拆分工作流时删除对应旧实现，避免同一工作流维护两套逻辑。目录名称变化不能改变工具 key、工作流 key 和数据库表名。

## 3. 能力边界与依赖

| 能力 | 负责 | 不承担 |
|---|---|---|
| Agent | 组合能力、运行图、模型交互、产出候选结果 | 自行审批、修改任务调度状态、复制业务执行器 |
| Tool | 明确输入输出的受控操作；适配业务服务 | 实现另一套业务规则、执行模型提供的任意代码 |
| Skill | 可复用方法、约束和领域指导 | 作为项目事实库，或自行授予工具权限 |
| Knowledge | 项目事实、版本、解析、检索与来源定位 | 根据业务含义保存正式流程或默认向所有 Agent 注入全文 |
| MCP | 外部服务连接、协议、发现、审批复核 | 承担任务状态管理、知识库本地数据模型或通用业务编排 |
| Tasks | 任务生命周期、运行实例、尝试、预算、事件与回执 | 解析 Skill 文件树、拼 MCP 协议请求 |
| Business assembly | 业务草稿、人工编辑、修订校验、事务保存 | 文档格式解析、底层 Agent 框架或正式业务主表复制 |

依赖方向：

```text
features/tasks → agents/services → assembly / workflows
agents → skills/services + knowledge/services + tools
tools/builtin → 所属 features 的公开 services + knowledge/services
tools/adapters/mcp → mcp/services
features/agent_governance/router → 各能力的公开 services
features/business_assembly → features/business 的公开 services
```

约束：

- `tools`、`skills`、`mcp`、`knowledge` 不反向依赖 `agents`、任务 Worker 或治理聚合服务；编排放在上层。
- 业务服务可经明确公开契约使用 Skill 渲染或模型能力，不得为此反向引用 Agent 图、节点或组装器。无领域依赖的公共基础能力归 `core/`；Feature 不因兼容入口反向依赖 Agent 图或业务编排。
- 各模块用 `services/__init__.py` 暴露公开入口，不新增跨包 `_access` 或私有函数依赖。原工具中涉及的私有鉴权调用需在对应业务模块提供公开服务入口后替换，保留原有权限行为。
- 工具调用上下文由服务端注入用户、项目、运行、尝试和确认凭证等引用；模型参数不能覆盖身份与审批信息。契约放在 `tools/contracts.py` 等中立入口，不导入 `NodeContext` 或 `AgentState`。
- 普通工具处理器不得调用任务管理服务。任务工具回执由任务适配器围绕调用入口记录；需要通用回调时依赖窄接口，由任务层注入实现。

## 4. 统一工具入口的要求

保留现有本地工具函数的参数和业务行为，先通过显式注册绑定处理器，再逐条切换调用点。工具规格至少描述稳定 key、输入契约、风险类别、实现绑定与当前可用状态；有副作用的操作补充人工确认和既有幂等/回执策略。

不能把当前 `catalog_only` 工具全部自动开放给模型。注册目录、固定工作流节点调用、LLM 可自由选择的工具是不同状态，必须保留现有执行范围。拆出 dispatcher 也不代表已经具有跨业务系统的统一事务或“恰好一次”能力。

工具目录中的稳定 key、任务运行使用的名称和 MCP 函数名现有映射要显式维护。例如 `execution.create_test_run` 与 `test-run.create` 不能因目录迁移直接改名。MCP 保留 `mcp:<server_id>:<tool_name>` 等实际引用格式；不从模型传入的任意路径动态导入处理器。

## 5. Skill、MCP 与知识的组合

Skill 首先复用数据库中的 `content`、`files_json`、版本和使用记录。`skills/builtin/` 仅用于明确需要随代码维护的资源；不把已有数据库内容自动复制到文件系统形成双写源。加载 Skill 关联的 MCP 工具只声明依赖，实际使用还须通过当前审批、任务范围和授权。

MCP 首先迁移现有实现，不新增未经验证的传输方式。继续限制为当前允许的已审批只读 Planner 工具；保持禁用、撤销审批、只读声明变化后的调用拒绝行为，子 Agent 不因重构获得工具权限。

知识库按项目隔离，知识与 Skill 分开管理。后续接入遵循：

1. Agent 模板可提供默认知识库选择，运行时解析为明确的库、文档版本和章节范围，不改变任务项目归属。
2. 运行快照保存知识范围和检索配置；每次访问仍重新校验当前权限、文档有效状态。旧任务缺少知识字段时按空范围处理。
3. 检索返回文档版本、分块标识、章节/页码和有限正文，草稿记录字段与来源的关联；正文不写入公开任务事件。
4. 全文业务组装先按目标章节提取、记录覆盖，再用检索补充细节；不能仅凭 top-k 片段声称全文覆盖。
5. 文档更新、停用、删除及权限撤销使新访问和缓存失效；历史正式业务不级联删除，原文保留策略按知识计划执行。
6. 首期按既有计划使用 PostgreSQL 关键词/章节检索；向量检索按实际效果另行评估，不在目录重构中新增向量数据库。

业务组装链路为 `tasks → agents/workflows/business_assembly → tools → knowledge / api_catalog / business_assembly services`。人工确认保存走业务草稿服务和正式业务聚合服务；不借此触发测试、扫描或通知。

## 6. 模型、HTTP 与历史任务兼容

- 模型只在所属能力定义一次；迁移治理模型时拆分 `AgentDefinition`、`SkillDefinition`、`MCPServer`、`ToolDefinitionOverride` 等的 Python 归属，保留表名、外键、索引和历史行。
- `SkillUsageEvent` 由 `skills` 持有，任务创建经其公开服务登记；外键可指向 Agent 和任务，模块不得因此导入任务运行服务。
- 不把所有新包模型加入 `app/core/models/__init__.py` 顶层导入。沿用九张基线表隔离；`app.models` 保留历史公开名称懒加载并转发到唯一新类。
- 检查 `backend/alembic/env.py`、历史迁移中的运行时代码导入和测试 fixture。只调整当前装配/必要兼容入口，不编辑历史迁移；在新进程验证空库升级与现有库升级，防止 `0001 create_all` 提前注册后续表。
- 纯 Python 文件移动不产生数据库结构迁移；知识库新实体等实际结构变化才从当时真实 head 新增显式迁移。
- HTTP 继续使用 `/api/v1` 和既有 `/agent-governance/*`、Agent 会话、任务接口。物理目录独立不要求 HTTP 路径同时改名，治理路由只做聚合转发，不能重复挂载同一路径。
- 保留 Agent、Skill、工具与 MCP 的 key/ID、配置 JSON、运行快照、审批信息和使用记录。旧运行仍按原快照解释，当前撤权依然生效。
- 旧导入路径可保留单向 re-export，不保留第二套模型和实现；清理内部旧引用后再移除兼容入口，历史迁移必需入口单独保留并说明原因。

## 7. 阶段与交付范围

| 阶段 | 改动 | 出口 |
|---|---|---|
| R0 | 核对当前代码、旧调用点、模型注册、任务快照和测试；记录目录与行为基线 | 确认已实现能力及迁移映射，不按历史 P0–P6 重做 |
| R1 | 工具按领域迁出，建立最小注册/调用契约和兼容导出 | 旧图和任务真实调用同一套工具，工具 key、权限与回执不变 |
| R2 | 拆分治理中的 Skill、MCP、工具配置和 Agent 配置 | 旧治理接口兼容，模型唯一，版本、审批和导入行为不变 |
| R3 | 提取 Agent 组装、快照、Skill 渲染与 MCP 适配 | 任务服务/Worker 经窄接口调用，租约、命令与副作用回执仍归任务层 |
| R4 | Agent 本体迁入 `app/agents`，图先迁 legacy，再按需要分领域 | 旧会话、API/Web/安全/报告工作流的状态、边与人工暂停行为保持 |
| R5 | 若知识库已在执行环境实现，迁入 `app/knowledge` 并接通知识工具 | 无重复知识实现，项目隔离、来源和版本可追溯 |
| K1–K3 | 若知识库仍未实现，按知识计划开发接入检索、草稿生成、人工保存 | 单独功能交付；不混入 R1–R4 的完成声明 |

R1–R4 是现有能力结构重构；R5 是条件迁移；K 阶段为后续产品开发。当前没有知识实现时不创建空壳并标记完成。执行要求及验收见 [09](09-optimization-requirements.md)。

## 8. 与其他文档的关系

本文件更新的是 Python 目录与能力归属，R0–R4 落地状态及路径见[目录重构交付记录](directory-refactor-delivery.md)。它替代旧方案中 `features/agent_registry`、`features/skills`、`features/tool_registry` 及知识计划中的 `features/knowledge` 路径建议。任务附件与项目知识库仍是不同产品资源；没有附件实现时不预建 `features/task_files`，有实现时通过资源引用对接知识服务，保持原可见性和保留策略。

原 01–06 中的任务协作、权限、幂等、恢复和人工确认要求继续有效；历史 P0–P6、旧交付记录不是本轮实际实现状态。编码规范描述当前代码结构，实施 R1–R4 时同步更新其目录与模型归属说明，不提前宣称目标结构已经落地。
