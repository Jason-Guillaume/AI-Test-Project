# 后端综合拆分工作包：一次委托、连续实施、统一交付

本文将后续后端目录与职责拆分整合为一个大工作包，列明完整范围、工程量、目标路径、内部依赖、验证与交付规则。执行 Agent 接收总需求后连续完成 B0–B9，内部检查点用于验证和恢复，不要求用户逐包重新下达指令。

编制日期：2026-10-29。当前依据为工作区源码和 [F0–F4 稳定化记录](backend-stabilization-delivery.md)，最近完整验证为 **1042 passed、0 failed、0 errors、0 skipped、47 warnings**。这是已记录的基线，实施开始时仍需核对是否存在新改动。本次仅编制计划，未执行下面的代码重构。

[返回索引](README.md) · [总需求提示词](19-backend-comprehensive-agent-prompt.md) · [逐项测试资产](backend-stabilization-validation/20261029-post-fix/summary.json)

## 1. 总体目标和统一实施范围

一次性完成执行契约、任务服务与运行时、安全测试、接口目录、测试数据、业务执行、Web 服务、Agent 服务边界及 Schema 的后续拆分，收口它们之间的公开契约和生产调用。

本文覆盖原 D1–D4、任务 T4–T6 及相关领域内部整理，替代早期“默认只执行 D1 或等待下一批指令”的范围限制。R/C/T/E/F 已有实现继续复用，不从旧方案重建。默认完成 B0–B9 全部工作包，不把完成一个工作包当作整个任务结束。

保留现有 `core/`、`execution/`、`llm/`、`agents/`、`tools/`、`skills/`、`mcp/`、`features/` 顶层布局。业务 ORM 继续归领域；平台核心 ORM 继续归 core。主要调整域内职责，不引入微服务、队列中间件或新的架构框架。

### 不纳入本单的产品范围

- 知识库、业务组装产品、E5 新工具、Agent 扫描审批新 UI、真实外部 ZAP 部署与扫描验收。
- 前端大规模拆分、数据库结构或迁移链重做、接口改版、框架升级、新的规则/脚本执行能力。
- 为追求文件数量或单纯减少行数而移动简单模块；无需处理用户、组织等已明确的小模块。

外部真实能力未验收的限制继续保留。实现中遇到与重构直接相关的缺陷，做最小修复并附行为验证；不要借机扩大产品范围。

## 2. 当前体量与工程量估算

2026-10-29 定向统计覆盖九个相关源码区域约 5.6 万行 Python，其中包含 ORM、现有服务与测试替身；这不是需要重写的代码量。较集中的实现有 TaskWorker 1964 行、TaskService 1291 行、ZAP connector 1116 行、orchestrator 1108 行、API 主服务 1034 行和多个 700–900 行 Schema。

| 工作包 | 实施内容 | 粗估工程人日 |
|---|---|---:|
| B0 | 源码/接口/状态/测试基线与依赖清单 | 1–2 |
| B1 | 公共执行契约、数据准备和按目标类型的执行适配 | 2–3 |
| B2 | 任务运行创建、方案批准与控制命令服务 | 2–3 |
| B3 | 任务处理器、租约、恢复、完成与失败协调 | 3–4 |
| B4 | 安全测试执行、ZAP 连接与扫描阶段编排 | 3–5 |
| B5 | 接口目录服务、请求定义、关系与响应转换 | 2–3 |
| B6 | Fixture 校验、依赖图、生成与清理生命周期 | 2–3 |
| B7 | 业务动作/流程、Web 服务、Agent 管理/会话边界 | 2–3 |
| B8 | Schema、路由、公开服务入口和跨域引用统一 | 1–2 |
| B9 | 完整回归、差异审计、文档及整体交付 | 2–3 |
| **合计** | **一单覆盖 B0–B9** | **20–31** |

这是按人工实现、联调和验证估算的工程量，不等于 Agent 运行天数或固定交付承诺。已有测试覆盖可减少摸索；跨域事务、运行恢复和现有工作区差异会增加耗时。执行以真实结果为准，不因估算耗尽而把未完成项标为完成。

## 3. B0：保存本次可比较基线

- 核对当前代码、已有本地改动、测试配置和 F 阶段逐项清单；必要时复跑最新基线，不直接把旧报告当当前结果。
- 保存本轮纳入源码的内容摘要/可恢复补丁、未跟踪源码清单和版本信息。仅 HEAD 不足以描述当前大量本地变更；不要复制 `.env`、凭据、登录态或归属不明的数据文件作为“快照”。
- 列出全部现存入口的目标归属，记录路由 method/path、请求/响应契约、工具 key、任务状态和回执键、人工确认边界、各主要 commit/flush/rollback 与外部 IO。
- 建立工作包跟踪表与测试 nodeid 清单；每包写明“未开始/实施中/已验证/受阻”、实际变更路径和下一步。
- 首先保护 F 阶段新修复的 ZAP 装配、治理引用保护、HTTP null/UTF-8/总超时、pytest 收集和浏览器登录；不在新拆分中退回旧实现。

## 4. B1：执行契约、准备和目标适配

目标根目录：`backend/app/features/test_management/executors/`。

| 建议路径 | 承接职责 |
|---|---|
| `contracts.py` | CaseExecutionResult 等公共执行结果/输入契约，唯一真实定义 |
| `preparation.py` | 断言配置、用例数据和执行前输入准备的公开入口 |
| `adapters/api.py` | API 目标适配，调用现有 execution/http |
| `adapters/business.py` | 业务动作/流程适配，调用 business 公开执行能力 |
| `adapters/web.py` | Web 目标衔接，调用受控浏览器领域入口 |
| `test_case_executor.py` | 统一分派、生命周期衔接和原公开执行入口 |

消除 `web_ui/runtime/adapter.py` 对 `_load_assertions/_load_data_values` 等私有实现的引用，以及安全执行对测试执行私有准备函数的依赖。结果契约和数据准备可被明确消费者复用，不复制第二套读取/解析逻辑。

断言判定、用例启用状态、Fixture 生命周期、变量优先级、Faker 生成时机、浏览器确认和业务执行记录保持原行为。业务绑定与映射只由 business 公共动作执行能力持有，不在测试适配器中再次实现。不是把这些领域协调搬进通用 HTTP 或 core。

## 5. B2：任务写入服务与状态协调

目标根目录：`backend/app/features/tasks/services/`。复用已存在的 query/message/resource/access/serializers，不重复提取。

- `run_service.py`：运行创建、参与者实例和快照持久化；依赖解析继续复用 agents/assembly。
- `plan_service.py`：方案版本、批准范围校验、计划采用和工作项/依赖入队。
- `command_service.py`：暂停、恢复、取消、重试的状态校验与幂等应用。
- 事件与状态归并若确有重复，提取窄的事件/状态协调入口；不建立通用事件平台。
- `task_service.py` 保留外部稳定门面和必要协调，不保留上述操作的第二份主体逻辑；message_service 等不反向依赖门面私有方法。

逐路径保持原行锁、事务拥有者、批准版本、命令键、运行号与资源回执。拆分不能让多个子服务分别提交原本必须原子完成的状态变化。既有服务内部提交和外部 IO 的现实边界先标记，再做行为等价提取。

## 6. B3：任务运行时完整拆分

目标根目录：`backend/app/features/tasks/runtime/`。

```text
runtime/
├── worker.py                    # 启停、主循环、分派与运行时装配
├── contracts.py                 # 明确的可信上下文和窄能力接口
├── lease_service.py             # 领取、续租、过期恢复及所有者代次
├── completion_service.py        # 完成、失败、重排与状态收敛
└── handlers/
    ├── planning.py
    ├── api_execution.py
    ├── security_execution.py
    ├── web_authoring.py
    ├── reporting.py             # 复用已有提取
    ├── reviewing.py             # 复用已有提取
    ├── chat.py
    └── finalizing.py
```

处理器使用明确参数或窄协议，不传入完整 Worker/TaskService，不用万能字典、反射导入、多继承 mixin 或大量私有回调隐藏耦合。现有 `Callable[..., Any]` 等宽接口在真实调用需要明确时收紧，但不为类型美化扩大业务改动。

租约/心跳保持独立 Session、行锁和代次；控制命令在原安全边界生效；迟到结果不得覆盖新尝试。任务、扫描与浏览器资源的所有者保持唯一。外部副作用状态不明继续按既有回执处理，不增加盲目重放。Worker 生命周期不因提取而重复启动或遗留线程。

## 7. B4：安全测试与 ZAP 域内整理

现有模型、队列、权限和审批留在 `features/security_testing/`。生产拆分优先于体积较大的 Mock 替身。

| 当前集中位置 | 建议提取到 |
|---|---|
| `runtime/runner.py` 中请求准备、候选处理、结果/证据持久化 | runtime 下职责明确的 preparation、case_runner、result_writer/evidence 模块；runner 保留协调 |
| `zap/connector.py` 中版本/能力、上下文、认证、导入、爬取和扫描操作 | `zap/protocol/` 下相应能力文件，connector 保留公开客户端门面 |
| `zap/orchestrator.py` 的准备、认证、爬取、被动/主动扫描、导入阶段 | `zap/stages/` 下独立阶段处理器，orchestrator 保留阶段推进与资源释放 |
| `zap/services/job_service.py` 中计划/审批、查询、命令的混合 | 独立计划、查询和命令职责，保留公开业务入口和事务协调 |

保留目标 scope、危险方法、认证复核、人工批准、扫描上限、取消、进度/心跳、证据脱敏和 Finding 去重。纯协议模块不查数据库，阶段协调负责状态与检查点；原 ScanWorker 继续唯一领取扫描队列，统一任务仅关联与跟踪结果。

不为了拆分将所有 ZAP 业务搬到 execution/http，不启用真实外部扫描验收，不扩展主动扫描授权。

## 8. B5：API 目录服务按资源拆分

目标根目录：`backend/app/features/api_catalog/services/`。

- `interface_service.py`：接口 CRUD 和项目归属校验。
- `module_service.py`：模块树、移动、唯一命名和计数。
- `request_service.py`：参数、Body、响应定义和请求 bundle 的公开读写。
- `relation_service.py`：接口关系管理。
- `change_service.py`：变更摘要、hash 与历史记录。
- `response_mapper.py`：纯响应转换，查询所需数据由服务明确加载。
- `api_service.py` 如需保留公开 facade，仅做委托，不再次包含完整实现。

现有 import/debug 通过公开契约协作，清理本轮涉及的私有 `_load_*` 跨服务调用。结构化格式 parser 保留格式职责，不为行数较长强制拆散语法解析过程。保持导入预览、去重、模块解析、hash、参数覆盖和调试返回语义，HTTP 继续走共享发送器。

## 9. B6：测试数据准备与 Fixture 生命周期

目标根目录：`backend/app/features/test_data/`。

- 将 fixture_service 的步骤/输出校验、依赖环检测、引用作用域、依赖边协调和响应转换分到明确模块；创建/更新/替换的写入事务仍由服务统一持有。
- 从 runtime/data_factory 中区分依赖执行计划、Provider 分派、上下文/输出归并和执行记录持久化。复用当前 providers 与 execution/templates，不复制模板或数据访问驱动。
- Fixture 清理与生命周期独立公开入口，保持 prepare/cleanup 顺序、失败策略、资源归属、池数据领取和回收、幂等及输出优先级。
- 数据库 Provider 的只读/写入边界、SQL Identifier 与值绑定、环境/连接授权保持；不增加任意 SQL/脚本执行能力。

共享纯算法与领域策略分开。依赖图与变量值不能因服务实例全局缓存跨项目或跨运行串用。

## 10. B7：业务执行、Web 与 Agent 服务边界

这是对现有领域内部职责的收口，不重写工作流。

| 领域 | 本单目标 |
|---|---|
| business | 将 business_flow_executor 的公开动作执行、流程顺序协调、输出/状态归并分开；输入输出映射与前置条件仍归业务；测试和 Data Factory 复用唯一动作入口 |
| web_ui | 按页面对象、用例确认、认证配置、执行/附件查询拆分当前 WebUIService；浏览器句柄/线程/配额仍由原 session_manager 管理，不移入任务快照 |
| agents | 从 agent_service 分离定义/修订、工具治理协调和 Skill/MCP 引用协调；从 session_service 分离状态重建、轮次持久化与响应装配，明确公开服务 |
| 治理路由 | 保持已修复的跨能力引用保护接线；协调放在上层，skills/mcp 不反向依赖 agents；HTTP 聚合可以保留 |

Agent legacy 图的边、暂停点和会话恢复保持；本单不要求改成另一套多 Agent 框架。报告提示词归 reports、通用模型调用归 llm 的边界继续保持。只在确有独立职责时拆文件，不能复制一套图来假装按领域完成提取。

## 11. B8：Schema、路由及公开入口统一

- 将 test_management、test_data、security_testing、business、api_catalog 中混合多个资源的 schemas.py 按资源拆为 schemas 包，按实际依赖需要排序实施，不机械生成每模型一个文件。
- 对外仍使用原 `app.features.<domain>.schemas` 公开 Python 入口；包 `__init__.py` 显式导出 canonical DTO 是正常公开 API，不等于恢复已清理的旧代理文件。不要通配转发或定义同名两份模型。
- 保持 wire 字段、默认值、校验、错误、OpenAPI schema 名称、枚举、分页和序列化语义；Pydantic 字段名告警不通过直接改 API 字段消除。
- 大 Router 按资源拆为 router 包时仍由 main.py 唯一挂载领域路由，保留 method/path、权限、响应码和 Mock catch-all 顺序。新增路由文件不能再出现“文件存在但未挂载”。
- 所有跨域业务调用通过公开 service/contract；对必要只读模型引用显式说明，禁止引用别域 `_` 实现。清理死引用和纯冗余代码，但不恢复 app.shared/app.models/features.agent 等删除入口。

## 12. 统一执行方式与内部检查点

工作包是同一请求的内部执行单元，不是十次用户审批：

1. B0 完成后按依赖推进 B1、B2、B3；涉及 B1 的安全/Web 调用同时完成迁移，不能让中间代码处于双主体状态。
2. B4 使用稳定后的执行/任务契约，B5/B6 按各自依赖继续；B7/B8 与前面领域提取的必要接口同步，避免最后一次性重改所有引用。
3. 每包运行受影响的最小行为验证，发现本轮回归先修复再继续。纯移动通过验证后直接进入下一包，不反复等待“是否继续”。
4. 至少在“执行与任务 B1–B3”“安全域 B4”“其余领域与 Schema B5–B8”三个跨域检查点，以及最终 B9 运行后端完整回归。若某一检查点同时构成最终验收，可合并同一份全量运行，避免无新增变化时重复测试。
5. 常规命名、文件合并、依赖顺序和兼容调整由 Agent 在范围内决策。只有不可替代的外部条件或必须扩大产品/破坏性范围时请求必要信息；测试失败、文件较大或完成一包本身不构成结束整单的理由。
6. 长任务持续维护进度记录。上下文压缩后依据记录继续，不从头重做；若受真实运行限制结束，明确已完成、未完成和下一步，不能把部分结果描述成整单完成。

默认不要求额外 Agent 或新聊天。执行者可以使用已有工具完成本单；用户不需要每次重新发一个子任务。

## 13. B9：整体验收与交付

必须满足以下条件，才能声明综合拆分完成：

- B0–B8 每包有真实实现路径、生产调用迁移与行为证据；没有空目录、双份主体、广泛反向私有依赖或绕过新入口的旧生产路径。
- 保持现有全部业务能力、人工批准、模型/工具范围、任务状态、事务和副作用回执；不只编译通过。
- 将原 1042 个 nodeid 与最终测试逐项比较。新增测试允许增加数量；参数化或文件移动导致 nodeid 变化时提供一对一/一对多的覆盖映射。不能靠删测试、跳过、弱化断言或改成功 Mock 达到全绿。
- 后端全量实际 0 failed、0 errors、0 unexpected skipped，公开接口契约与资源权限回归通过，pytest 默认入口继续只收集真实测试。
- F 阶段的路由/生命周期、Skill/MCP 引用保护、真实 HTTPX 编码、UTF-8、总预算、浏览器登录与跨项目隔离继续通过。
- 全量报告含收集数量、通过/失败/错误/跳过、warnings 分类、代码内容标识、命令和耗时；原 47 条 warning 不要求靠升级框架全部清零，不增加无说明的新警告或全局过滤。
- 无数据库结构变更，无新增迁移，无明文凭据/登录态进入源码、测试产物或公开日志；历史迁移不因域内搬文件而修改。

测试复用当前 `backend/tests/` 全量，相关专题包括 test_executor、business、Data Factory/生命周期、Mock、安全/ZAP、Web/Agent、任务/通知/治理、核心注册和业务能力提取。B0 生成各包实际 nodeid 与文件清单，避免只运行几条 smoke 测试。

所有数据库验证使用显式配置的隔离 PostgreSQL；本地浏览器/HTTP 服务和 Fake/Mock LLM/ZAP/通知覆盖执行路径，不访问开发/生产数据、不执行真实外部扫描或通知。不把独立生产部署验收当作本单隐含要求。

### 唯一交付入口

执行期间维护 `docs/agent-cluster-refactor/backend-comprehensive-progress.md`，保存包状态、方法/路径映射、检查点、实际失败与下一步。

收尾创建 `docs/agent-cluster-refactor/backend-comprehensive-delivery.md`，汇总全部 B 包、最终目录、公开契约、事务/回执保持方式、nodeid 对比、全量结果、warnings、剩余限制与回退方案。脱敏机器报告统一保存至 `docs/agent-cluster-refactor/backend-comprehensive-validation/<run-id>/`。本次编制不预填成功记录。

同步现行编码规范、相关架构与模块说明和文档索引；R/C/T/E/F 历史交付记录保留原事实，只增加后续入口，不改写其测试结果。

## 14. 代码组织与回退约定

文件大小以职责为准；200–500 行可作复核参考，不能作为强制切片标准。较长的格式解析、协议数据、纯测试替身可有合理例外，交付中说明；大型 coordinator 不能只换名或拆成相互调用私有方法的碎片。

规范公共 facade 和 package exports 可以保留，必须无第二份业务实现且有真实消费者。不要为每次内部移动增加永久兼容层，也不要为消除导入路径而破坏真实契约。

保持按工作包可恢复的代码变更与证据，不把用户其他本地改动混入回退。没有 schema 改动不降库；真实执行/报告/数据产物不因代码回退删除；运行所有者唯一，不并行启动新旧调度和扫描主体。
