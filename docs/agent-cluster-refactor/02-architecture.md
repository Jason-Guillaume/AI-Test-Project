# 后端架构、数据与运行机制

说明当前代码依据、模块与数据模型、调度恢复、权限和接口草案；协作规则见协作协议。

编制日期：2026-10-26。状态：待实施设计；原始代码核对日期同上，实施时必须重新核对当前代码与迁移 head。

[返回文档索引](README.md) · [实施交接指令](07-agent-handoff.md)

> 2026-10-28 更新：下方“已核对的现状”是 2026-10-26 历史快照；当前代码已有任务运行、Agent/Skill 治理和 MCP，旧迁移编号和“未发现”结论不能用于判断今天的实现。`app.models`、`app.shared`、旧 `features/agent` 与纯转发页面入口已清理，实际模块以规范路径为准。当前能力目录与迁移方案见 [08](08-directory-refactor.md)，执行需求见 [09](09-optimization-requirements.md)。原运行一致性、权限、人工确认与协作约束继续适用。

> 2026-10-29 更新：跨业务域 HTTP、表达式、LLM 与模板能力已按 E0–E4 提取，当前实际路径和回归结果见[业务能力提取交付记录](business-capability-extraction-delivery.md)；下方仍属任务产品架构设计的内容继续按历史设计看待。

> 2026-10-29 目录归属更新：当前平台管理模块位于 `backend/app/platform/{users,organizations,projects,environment_configuration,model_configuration,notifications,agent_governance}/`，任务编排位于 `backend/app/orchestration/tasks/`；`backend/app/features/` 保留 api_catalog、business、mock_management、security_testing、test_data、test_management、web_ui、defects、reports、dashboard 十个业务模块。任务编排通过 WebUIService 调用 Web UI；任务运行和 UI Worker 绑定由编排层注入 `TaskBindingValidator` 校验，Web UI 仍在入口处检查项目写权限和执行环境。具体迁移映射、基线和验证限制见[features 目录迁移交付记录](features-directory-layout-delivery.md)及[迁移前基线](features-layout-baseline.md)。


> 2026-10-30 后端能力边界整改：项目访问契约统一归 `platform/projects/services/access_service.py`；组织管理和通知收件箱业务分别由平台服务持有；报告投递由 `orchestration/report_delivery/` 协调；任务模型提示词和候选生成归 `agents/services/task_decision_service.py`，任务状态、工具回执及事务仍由 `orchestration/tasks/` 持有。正式 Web 业务现位于 `features/web_testing/`，完整 Mock 能力位于 `features/mocking/`；浏览器探索生命周期归 `agents/browser_authoring/`，唯一 Playwright 执行器、观察器和会话资源注册表归 `execution/browser/`。`WebAgentSession` 与 `WebAgentStep` 仅有一套 ORM 定义，表结构未改。具体迁移、C01–C12 取舍及本次验证见[后端能力边界整改交付记录](backend-capability-refactor-delivery.md)。

## 已核对的现状及改造结论

| 当前实现 | 代码依据 | 改造结论 |
|---|---|---|
| Agent 由 HTTP 消息同步推进固定 LangGraph，按自建会话表重建状态 | `backend/app/agents/router.py`、`workflows/legacy/graph.py`、`services/session_service.py` | 原工作流可作为兼容适配器；需要新增请求之外的任务运行与调度层 |
| Agent 会话按 project + user 隔离，保存阶段和消息 | `backend/app/agents/models/session.py` | 不直接将旧会话改名为任务；新增任务、运行、参与者及会话关联 |
| 工具已封装接口查询、资产保存、测试执行、报告与安全扫描 | `backend/app/tools/builtin/` | 优先提炼契约与适配器，复用现有服务；避免各 Worker 重写执行器 |
| Agent 执行会创建临时测试计划和套件，再调用 RunService | `backend/app/tools/builtin/test_management/execution_tool.py` | 增加可追踪的调用幂等键；重试不能重复创建计划或执行记录 |
| 默认模型从启用且默认的模型配置加载 | `backend/app/llm/providers/openai_compatible.py`、`backend/app/platform/model_configuration/services/model_config_service.py` | Agent、报告、Web 与任务通过共享 Provider 使用模型；模型配置和资源授权仍归 platform/model_configuration 与上层调用方 |
| 已有模型配置与加密密钥管理 | `backend/app/platform/model_configuration/` | 复用模型资源，不另建密钥仓库；项目用户只选择被授权的模型配置 |
| ZAP 已采用数据库队列、领取、心跳和取消标记 | `backend/app/features/security_testing/zap/worker.py` | 借鉴该模式设计通用运行时；不把扫描专用 Worker 直接当作通用调度器 |
| Web 交互会话句柄位于进程内，并有专属线程和资源上限 | `backend/app/features/web_ui/runtime/session_manager.py` | 新调度器必须识别资源归属；不可承诺跨进程恢复活浏览器句柄 |
| Web 探索步骤、正式用例执行、安全扫描都有既有确认约束 | `backend/tests/test_33_web_agent_loop.py`、`test_32_zap_agent_approval.py` | 新角色、调度器和工具必须继续通过这些约束；AI 审阅不能代替人工确认 |
| 控制台已有组织/项目上下文、菜单与业务路由 | `frontend/src/layouts/ConsoleLayout.tsx`、`hooks/useConsoleScope.tsx`、`App.tsx` | 全局助手挂在路由出口之外；原有管理页面保留 |
| 当前客户端使用 Bearer 请求头，普通请求超时为 30 秒 | `frontend/src/api/client.ts` | 长任务提交后立即返回，事件初期采用游标轮询；后续再扩展流式通道 |
| 最新迁移为 0014 | `backend/alembic/versions/0014_web_agent.py` | 新迁移从实施时的实际 head 追加，不修改历史迁移 |

本轮未发现统一任务域、运行时 Agent / Skill / Tool 注册中心、通用会话附件解析链路或任务事件流实现。以上是本次定位范围内的结论，不替代后续实施前的定向复核。

## 后端模块与最小数据模型

### 目标模块（2026-10-28 修订）

- `app/orchestration/tasks/`：保留已有任务、运行、方案、参与者、命令、事件、租约和回执，不重新建设。
- `app/agents/`：Agent 定义、会话、能力组装、运行快照及分领域工作流；模型调用依赖独立 `app/llm/`。
- `app/llm/`：通用 Provider、调用契约与追踪；不承载 Agent 图、任务或报告资源。
- `app/execution/`：跨业务域 HTTP 执行、请求构建与模板解析；目标授权仍由 projects 等业务域提供。
- `app/tools/`：工具元数据、真实处理器注册、受控调用及按业务领域分类的薄适配。
- `app/skills/`：Skill 定义、版本、导入、文件树与渲染；Agent/任务使用统计由上层 Agent 服务聚合。
- `app/mcp/`：服务登记、连接、发现、审批和协议调用。
- `app/knowledge/`：项目知识库、文档版本、解析、分块、检索与来源读取；当前为待实现设计，执行时复核。
- `app/features/business_assembly/`：后续业务草稿、修订、来源关联、校验和保存协调；正式业务仍在 `features/business/`。
- `app/platform/agent_governance/`：保留治理 HTTP 路由；Agent、Skill、MCP 与 Tool 的业务实现位于各自规范包，旧 `features/agent/` 转发模块已删除。

以上替代原 `features/agent_registry/`、`features/skills/`、`features/tool_registry/` 目录建议。任务附件与项目知识具有不同可见性和生命周期，按真实需求以资源引用对接，不预建 `features/task_files/` 或复制知识处理链路。模块内部按需使用 `schemas.py`、`router.py`、`services/`、`models/`，跨模块通过公开服务与 DTO 协作，事务边界由服务层持有；详细映射及兼容见 08。

### 当前任务与领域职责（综合拆分 B0–B9）

统一任务公开入口保持 `TaskService`。运行与快照构造在 `services/run_service.py`，批准范围和工作依赖在 `plan_service.py`，幂等控制在 `command_service.py`，事件/状态归并在 `state_service.py`，Agent/模型授权装配在 `assembly_service.py`；既有 access/query/message/resource/serializers 继续复用。子服务使用同一 Session 协作，原提交点与行锁不拆散。

`runtime/worker.py` 保留唯一生命周期、分派和 Provider 装配；领取/续租/恢复在 `lease_service.py`，完成/失败/控制边界在 `completion_service.py`。planning、api_execution、security_execution、web_authoring、reporting、reviewing、chat、finalizing 各有真实生产处理器。模型调用后的暂停/取消边界、`report:<test_run_id>` 等回执与依赖保持；迟到完成/异常还会核验所有者与代次，避免旧线程覆盖新尝试。

执行契约与用例准备归 test_management，绑定/映射归 business，浏览器资源归 web_ui，Fixture 准备/清理归 test_data。API 目录按资源拆服务，安全测试的 IO 与纯算法分开，ZAP 的协议调用与扫描阶段分开。五个多资源领域的 `schemas/`、`router/` 包通过显式 canonical exports 与单一领域聚合挂载保持原 Python/HTTP 入口；原先的 T4–T6、D1–D4 待办已纳入本轮实施。全部职责和验收事实统一见 [综合交付记录](backend-comprehensive-delivery.md)，历史 T/E/F 报告保留原时点结果。

### 数据实体分阶段落地

| 实体 | 必要字段/用途 |
|---|---|
| `task` | 项目、发起人、目标、标题、范围、最新运行引用与归档标记 |
| `task_run` | 运行序号、状态、计划版本、预算、时间、暂停/取消意图与失败原因 |
| `task_plan` | 编排方案版本、目标分解、验收条件及采用状态 |
| `task_work_item` / dependency | 子任务、职责、输入/输出契约、必需/可选、依赖和状态 |
| `task_agent_instance` | 所属运行、角色、模板版本、配置快照与资源归属 |
| `task_agent_attempt` | 参与者执行尝试、租约代次、检查点、开始/结束与失败原因 |
| `task_message` | 发送者、接收会话、关联子任务、内容、回复关联和消费状态 |
| `task_command` | 暂停、取消、重试、方案采用等可靠指令，含幂等键、操作者与处理状态 |
| `task_event` | 运行内递增序号、事件类型、关联对象、脱敏内容与时间 |
| `task_resource_ref` | 输入/产物、原业务类型/ID/版本、产生实例和来源尝试 |
| Agent / Skill / Tool definition + version | 可复用配置、不可变发布版本和启用范围 |
| `tool_invocation` | 调用幂等键、工具版本、参数摘要、状态、业务回执与结果引用 |
| file / parse result / file reference | 存储引用、校验摘要、解析状态、内容块及任务可见关系 |

表名为建议，实施前按概念边界合并或拆分。首批只建对应阶段需要的表，初期配置绑定可以保存在版本化 JSON 中，避免提前扩展大量关系表。秘密值不进入配置快照和事件。

## 调度、恢复与一致性

### 状态语义

任务运行：草稿 → 规划中 → 待补充/待确认 → 排队中 → 运行中 → 完成/完成但有问题/失败/超时。

运行中可请求暂停或取消，先显示“暂停中/取消中”，到达安全边界后才进入“已暂停/已取消”。暂停保留可继续的运行；取消终止后续调度。已经发生的外部业务写入不会被这些操作自动撤销。

子任务分别记录等待依赖、可领取、运行中、待用户输入、待确认、成功、失败、取消和跳过。Agent 的某一轮模型调用结束，不等于子任务或整条任务完成。

必需子任务失败时，阻塞依赖它的后续步骤；可选子任务失败允许带问题汇总。报告明确覆盖范围和未执行项。重试只覆盖失败部分，计划变化产生新的方案版本与明确的结果失效规则。

### 执行机制

- 任务命令 API 持久化后立即返回任务/运行 ID；长执行不依赖 HTTP 连接和网页是否打开。
- PostgreSQL 存储可领取工作项。领取与状态更新在短事务内完成，使用行锁、租约和可校验的所有者代次。
- 项目、用户、模型、任务及浏览器/ZAP 等专用资源分别配额；额度领取须有原子约束，不能仅依赖“先统计再执行”。
- 外部 IO 与模型调用不长时间占用数据库事务。并发执行使用独立数据库会话，心跳与控制命令可独立推进。
- 结果回写校验 attempt / lease 代次，过期 Worker 的迟到响应不得覆盖新执行结果。
- 子任务和模型调用均有时间、步数、Token 与重试上限；返工与协作派生也计入任务预算。
- 首期采用一个受监督的通用运行服务，可在其中运行有限并发执行段；保持现有 API 单进程部署约束。增加任务 Worker 不等于直接扩大 HTTP API 进程数。

### 工具幂等与中断恢复

领取协议只能减少重复执行，不能保证跨外部系统的“恰好一次”。每个有副作用的工具必须声明幂等策略、查询回执能力、取消边界和恢复方式。

创建计划、保存用例、启动 TestRun 等操作以任务/子任务/逻辑操作键关联业务回执；同一操作重试优先查询已存在的记录。现有执行工具需要拆分或补充“创建/查询/继续”的适配契约。

进程重启后：可证明幂等的步骤从检查点恢复；已启动的执行/扫描按业务记录查询和收集结果；副作用状态不明确的步骤进入待核对状态，不能盲目重放。

UI 交互式会话维持 owner 归属，并在同一会话内串行执行。浏览器句柄丢失时先报告中断，按能力重建环境或请求重新确认；不宣称恢复到丢失前的页面内存状态。

### 事件与前端同步

首期采用已鉴权的游标事件查询，按运行内递增 `event_seq` 返回新事件。支持去重、分页补拉、断线续读和终态校准，禁止把流中断当作任务失败。

后续若增加 SSE，需要解决现有 Bearer 请求头、连接鉴权与撤销、心跳、游标续传和反向代理设置，不能直接把凭据拼在 URL 中。事件通道只承载已持久化事实；核心状态不依赖前端收消息。

## 权限、确认与上下文隔离

- 沿用现有平台/组织/项目角色，任务、文件、产物、消息与配置版本访问都执行服务端项目校验。
- 任务运行不提升发起者权限；每次关键工具调用重新确认用户有效性与当前授权，不向 Worker 分发原始登录 JWT。
- 工具可用范围取用户权限、项目范围、任务约束和 Agent 工具白名单的交集。
- 复用既有 Web 用例确认、交互步骤确认、安全扫描批准和通知确认。模型生成内容或质量审阅通过都不构成人工批准。
- 日志只保存必要参数摘要与结果引用。密钥、登录态和敏感请求值继续使用现有加密与脱敏能力。
- Worker 按分派接收文件和资产引用，不默认加载所有历史任务或所有项目文件。
- 任务内私有会话与项目可共享产物分开授权。旧 AgentSession 继续遵守现有 project + user 可见性，不因新增项目任务页自动扩大旧会话访问范围。
- 初期自定义工具仅注册已实现的平台适配器；MCP/HTTP 后续接入继续验证目标、连接凭据与出站策略。AI 生成工具定义不直接运行任意脚本。

## API 与前端契约草案

所有端点继续使用 `/api/v1` 前缀、现有错误信封与分页约定。下列为拟新增契约，实施前按服务拆分确认，不表示已存在。

| 契约 | 用途 |
|---|---|
| `GET/POST /projects/{project_id}/tasks` | 项目内创建与查询任务 |
| `GET /tasks` | 聚合当前用户可访问任务，支持项目/状态筛选 |
| `GET/PATCH /tasks/{task_id}` | 读取与修改未启动目标，运行中目标走方案变更命令 |
| `POST /tasks/{task_id}/runs` | 启动或重新运行，返回运行引用与接受状态 |
| `GET /task-runs/{run_id}` | 运行权威状态与汇总 |
| `GET /task-runs/{run_id}/agents` | 任务内参与者及会话列表 |
| `GET/POST /task-runs/{run_id}/messages` | 主 Agent / 指定参与者消息，服务端校验接收对象 |
| `POST /task-runs/{run_id}/commands` | 暂停、恢复、取消、子任务重试与采用方案版本 |
| `GET /task-runs/{run_id}/events?after_seq=...` | 可续读的持久化事件 |
| `GET /task-runs/{run_id}/resources` | 输入与产物引用 |
| 项目下的 Agent / Skill / Tool 定义及版本端点 | 草稿、校验、发布、停用与引用关系 |
| 文件上传、状态查询、解析与片段读取端点 | 文件处理与任务引用 |

创建运行、命令、消息和工具副作用应接受客户端请求标识并去重。审批命令必须关联方案/步骤版本与操作者，由真实鉴权请求生成，不能由模型字段冒充。

前端新增 tasks / agentDefinitions / skills / tools / taskFiles 的类型和 API 封装，全部复用 `api/client.ts`。事件到达后精确失效对应项目业务查询；不能只刷新任务页导致管理页长期显示旧资产。
