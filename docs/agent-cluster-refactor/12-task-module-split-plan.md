# 任务模块分阶段拆分与回归收尾计划

本文规划 `features/tasks` 内部的职责拆分、依赖和验收，供下一位实施 Agent 使用。当前只更新文档，未执行本计划中的代码修改或测试。

编制日期：2026-10-28。依据当前工作区及 [core 归并交付记录](core-consolidation-delivery.md)；实施时重新核对源码、已有改动和测试结果，不把历史失败数量当作当前实测。

[返回索引](README.md) · [Agent 需求提示词](13-task-module-split-agent-prompt.md) · [协作协议](03-collaboration-protocol.md) · [原运行架构](02-architecture.md)

## 1. 本轮目标和边界

将任务查询、响应转换、消息、资源引用以及报告/审阅处理从大型 `TaskService` 和 `TaskWorker` 中提取，保留既有公开入口和运行行为。减少增加任务类型时必须同时修改的大文件，不以行数、文件数或新建空包作为完成标准。

默认实施 **T0–T3**：回归收尾与基线、查询/转换、消息/资源服务、报告/审阅处理器。T4–T6 列出后续方向，本轮不提前移动运行创建、批准、控制命令、租约恢复和其他执行处理器的实现。T0 中与本轮直接相关的兼容修复例外，需记录证据。

不重做 Task/TaskRun 数据模型或任务平台，不重写原 Agent 工作流、测试/安全/Web 执行器，不修改前端、工具授权范围、接口、数据库结构或依赖版本，不新增框架、队列中间件、通用 Repository 或通用调度平台。

## 2. 当前依据与拆分风险

| 位置 | 已核对情况 | 本轮处理 |
|---|---|---|
| `backend/app/features/tasks/services/task_service.py` | 约 1616 行，含创建、查询、消息、命令、批准、运行构造、权限、资源与响应转换 | 先提取查询，再提取消息和资源；其余通过原入口协调 |
| `backend/app/features/tasks/runtime/worker.py` | 约 2162 行，含领取、续租、规划、执行、报告、审阅、控制边界、完成与恢复 | 本轮只提取报告/审阅处理及其必需窄接口 |
| `backend/app/features/tasks/services/__init__.py` | 当前公开导出 TaskService | 继续提供稳定公开入口，按实际使用增加专门服务导出 |
| `backend/app/features/tasks/router.py` | 路由调用 TaskService 与 Web 编写服务 | 路由行为不变，不把业务权限和事务移入路由 |
| `TaskService.send_message` | 存在消息去重、接收者校验、入队、事件和可能的新运行创建 | 提取不改变消息/运行/事件的事务和返回字段 |
| `TaskWorker._handle_report` | 创建正式报告、写工具回执和资源、消息、审阅依赖 | 不是只读操作，保留现有调用键、提交与恢复边界 |
| `TaskWorker._handle_review` | 读取正式事实、调用模型、复核统计和当前控制状态 | 不能只信模型结论；保留事实校验、脱敏及暂停/取消检查 |

core 交付记录记载一次全量运行有 `947 passed, 69 failed, 13 errors`，包括误收集 Agent 节点、Langfuse setup 和 ZAP/Web 相关问题；记录不证明这些失败的根因，也不能替代当前复现。已有库升级与数据保留验证仍未完成，独立保留为前轮待办，不借本轮拆分宣称已完成。

## 3. 目标目录与首批范围

路径均相对仓库根目录。只创建本阶段有真实实现的文件。

```text
backend/app/features/tasks/
├── router.py                         # HTTP 契约保持
├── schemas.py                        # 当前 wire 字段与状态保持
├── models/                           # 当前实体归属保持
├── adapters.py                       # 对既有业务能力的适配保持
├── services/
│   ├── __init__.py                    # 稳定公开入口
│   ├── task_service.py                # 外观与跨服务协调，旧公开方法保留
│   ├── access.py                      # T1：任务/运行范围鉴权，避免反向依赖外观
│   ├── query_service.py               # T1：任务/运行/消息/事件读取
│   ├── serializers.py                 # T1：无查询、无写入的响应转换
│   ├── message_service.py             # T2：消息校验、去重、记录与处理协调
│   ├── resource_service.py            # T2：资源引用、名称及来源查询
│   ├── web_authoring_service.py       # 当前实现保留
│   ├── run_service.py                 # T4：后续创建运行与快照持久化
│   ├── plan_service.py                # T4：后续方案批准及工作项入队
│   └── command_service.py             # T4：后续暂停/恢复/取消/重试
└── runtime/
    ├── worker.py                      # T3 保留生命周期、分派与运行控制
    ├── contracts.py                   # T3：处理上下文及窄协作接口
    ├── handlers/
    │   ├── reporting.py               # T3：原报告处理实现
    │   ├── reviewing.py               # T3：原审阅处理实现
    │   ├── planning.py                # T5：后续规划处理
    │   ├── api_execution.py           # T5：后续 API 执行协调
    │   ├── security_execution.py      # T5：后续安全执行协调
    │   ├── web_authoring.py           # T5：后续 Web 编写协调
    │   └── chat.py                    # T5：后续角色对话
    ├── lease_service.py               # T6：后续领取、续租与过期恢复
    └── completion_service.py          # T6：后续完成、失败与状态回写
```

`access.py` 是任务领域的访问检查，不下沉 core；使用现有 core 角色和项目可见性机制。`serializers.py` 不借属性访问偷偷查询；需要数据库的数据先由查询服务加载。

## 4. 方法与职责迁移映射

| 当前方法/逻辑 | 目标 | 阶段与要求 |
|---|---|---|
| `list_tasks`、`get_task`、`get_run_detail`、`list_messages`、`list_events`、`_latest_runs` | `services/query_service.py` | T1；保留过滤、分页、排序、游标、返回字段及权限 |
| `_task_response`、`_run_response` 等纯转换 | `services/serializers.py` | T1；有查询的 `_task_detail` 逻辑仍归查询服务，不机械搬入转换器 |
| `_get_project_for_read/write`、`_get_task_for_read`、`_get_run_for_read/write` 等 | `services/access.py` | T1；保留原查询锁和 404 行为，不将读写门槛统一放宽 |
| `send_message` 的消息处理逻辑 | `services/message_service.py` | T2；跨运行创建协调仍由外观负责，或注入明确的创建运行窄接口，不导入 TaskService 形成循环 |
| `list_resources`、`find_tasks_for_resource`、`_resource_display_names`、资源响应 | `services/resource_service.py` + 必要纯转换 | T2；保留批量名称查询和来源可见性，不新增 N+1 |
| `_add_resource_ref`、Worker `_add_resource` 等重复引用逻辑 | `services/resource_service.py` 的明确公开写入口 | T2/T3；先核对各调用方语义，保留唯一键与原提交归属，不强行合并有差异的方法 |
| `_handle_report` | `runtime/handlers/reporting.py` | T3；保留 `report:<test_run_id>` 调用键、正式产物、审阅依赖、资源和事件 |
| `_handle_review` | `runtime/handlers/reviewing.py` | T3；保留正式事实、统计核验、输出校验、脱敏和控制边界 |
| 处理器依赖的工具授权、模型 provider、事件、入队和控制边界操作 | `runtime/contracts.py` 中按需声明的窄接口，由运行层装配 | T3；不把整个 Worker 或 TaskService 作为上下文传给处理器 |
| `_create_run`、`_approve_plan`、命令处理及运行创建相关逻辑 | 后续 run/plan/command services | T4，本轮不整体移动 |
| 其他 `_handle_*` | 对应 handler | T5，本轮不整体移动 |
| `_claim`、`_heartbeat_loop`、`_recover_expired`、`_complete_work`、`_fail_work` | lease/completion services | T6，本轮保留实现位置与控制行为 |

外观可以临时保留私有转发以兼容已存在的测试或调用，但新子模块不能再通过这些私有方法调用外观。实施时搜索实际调用点，按依赖图决定迁移批次，不只剪切方法正文。

## 5. 依赖与事务规则

### 5.1 依赖方向

```text
router → services 的公开入口 → TaskService 外观协调
TaskService → query/message/resource/access/serializers
TaskWorker → handlers + runtime/contracts
handlers → 明确业务适配器/工具入口 + 任务窄协作接口
query/message/resource → task models + access + core + 所需公开能力
```

消息服务需要创建运行或入队时，使用明确的能力接口或由外观组合，不能反向导入外观；查询和响应转换不依赖 Worker。现有 `agents/assembly`、Skill 渲染及 MCP 适配保持归属，不搬回 tasks。纯模型生成工作流仍归 agents，handler 负责本任务内的执行协调。

不为拆分引入“万能 context”、动态导入处理器、反射路由、访问所有私有方法的回调集合或多继承 mixin。处理器按实际需要接收 `db`、任务/运行/工作项/尝试/身份以及少量有明确定义的协作能力。它们不能被模型输入伪造或覆盖。

### 5.2 保持事务与外部副作用

- T0 先标出各路径现有的 `flush/commit/rollback`、行锁、模型/外部 IO、调用回执与控制边界，再提取实现。不能一律“删除处理器 commit”或新增每个子服务独立提交。
- 纯查询和转换不提交事务。消息写入、工作项入队、事件及新运行创建保持当前有界事务语义；同一客户端消息键仍去重且返回兼容结果。
- 报告调用现有业务服务可能已有提交；保留 STARTED 回执、正式报告、成功回执和尝试回写的实际顺序，不假设它们天然是一个原子事务。
- 重试不得新造另一套报告回执键。外部副作用结果不明时按现有规则查询回执或等待核对，不能通过拆分新增无条件重放；发现既有幂等缺口应单列最小修复和验证。
- 保留原尝试/租约有效性复核、暂停/取消边界和迟到结果保护。报告或审阅 handler 返回后，仍由原运行控制路径决定工作项完成与后续派发。
- 审阅的模型结论不代替正式执行事实或人工批准；统计不匹配、范围不足和安全执行缺失仍必须影响结论。禁止因提取而删除确定性校验。

## 6. 阶段与进入条件

| 阶段 | 工作范围 | 出口证据 |
|---|---|---|
| T0 | 复现并分类前轮失败；核对 pytest 收集、Langfuse 替身和任务依赖的 ZAP/Web 问题；建立当前接口、状态、事件、回执与测试基线 | 与任务和公共导入有关的阻塞修复并通过定向验证；其他已复现无关问题记录证据，不笼统宣称都是旧问题 |
| T1 | 提取查询、响应转换和任务访问检查；原公开入口转发 | 查询响应与顺序兼容；跨项目访问拒绝；无查询写入；无循环依赖 |
| T2 | 提取消息与资源服务，保持事务协调 | 消息重复提交不重复入队；接收对象、终态运行处理、事件和来源回链一致；批量名称加载保持 |
| T3 | 定义窄处理契约并提取报告、审阅；Worker 调用真实新实现 | 正常链、权限拒绝、重复/结果不明、暂停/取消和事实核验均验证；原 Worker 不保留第二份主体实现 |
| T4 | 后续运行创建、批准、命令服务 | 另轮实施；验证原子状态变化、批准版本、控制命令幂等与并发 |
| T5 | 后续其余角色处理器 | 另轮实施；逐类型行为与人工确认回归 |
| T6 | 后续租约、恢复、完成/失败协调 | 另轮实施；领取竞争、心跳、中断与迟到结果验证 |

默认执行到 T3 即交付，不因目标树出现 T4–T6 文件就提前建包或移动实现。T0 不要求借此重做全部无关功能；无法建立可信的任务行为基线时，保留依赖该基线的阶段待办，并完成不受阻的盘点和验证，不盲目扩大重构。

测试收集修复可以明确限定真实测试入口，不能排除应执行的测试；Langfuse 等兼容问题需核对真实规范模块与 monkeypatch 绑定，不新增假的成功响应、弱化断言或跳过失败用例。

## 7. 验收与测试

优先复用现有测试，缺少的高风险行为增加定向用例，不为每个转发方法重复写测试。可使用当前运行时执行：

```bash
cd backend
.venv/bin/python -m compileall -q app tests
.venv/bin/python -m pytest tests/test_core_consolidation.py tests/test_27_langfuse_tracing.py -q
.venv/bin/python -m pytest tests/test_35_tasks.py tests/test_task_notifications.py tests/test_36_agent_governance_details.py -q
.venv/bin/python -m pytest tests/test_16_agent.py tests/test_26_security_agent_report.py tests/test_32_zap_agent_approval.py tests/test_33_web_agent_loop.py -q
```

按 T0 实际复现补跑 ZAP/Web 相关最小测试。测试前按当前 conftest 显式提供隔离 PostgreSQL 配置，凭据使用执行环境提供的值，不写入文档、代码、命令记录或普通日志；不自动复用开发库 DSN，不清空开发/生产库，不删除归属不明的数据库。

验收至少包含：

1. 任务/运行查询、消息、事件游标、资源列表与来源反查的权限、字段、排序、分页兼容；任务和项目上下文不串用。
2. 重复消息、非法接收者、运行已结束后的消息、消息触发新运行及相关事件具有可核对结果；不重复创建运行或入队。
3. 报告基于真实 TestRun 生成，保留正式报告、资源、工具调用记录、消息和审阅依赖；重复或中断后的行为与既有回执策略相符。
4. 审阅识别覆盖不足、统计不一致和安全事实缺失，不被模型 `approved=true` 覆盖；模型调用后到达暂停/取消边界不继续错误派发。
5. 模型异常、工具拒绝、任务暂停/取消及陈旧尝试结果仍通过原控制路径处理，错误和回执没有丢失。
6. 旧公开入口和必需的兼容路径仍调用新唯一实现；可通过真实 handler 测试确认没有空壳或循环依赖。

每批通过相关定向验证后推进，收尾运行后端全量回归，并分别报告“新增失败”“已复现基线失败”“未测项”。全量未通过不能标记全量验收通过；历史 path 数量相同也不能代替接口响应和业务行为验证。没有 schema 改动不新增迁移，不借本轮改写历史迁移或重新归并 core。

## 8. 交付与回退

实施 Agent 创建 `docs/agent-cluster-refactor/task-module-split-delivery.md`，记录开始基线、T0 失败分类及最小复现、T1–T3 实际方法映射、依赖图、保留的事务和回执边界、测试命令/结果、未测项及 T4–T6 待办。当前不预填实施成功记录。

同步更新本目录索引及任务架构/运行说明中的实际路径，保留原 R 阶段、core 归并和产品 P 阶段交付记录的历史事实。代码迁移落地后再更新现状目录，不能用目标树宣称所有服务和处理器已实现。

回退按阶段恢复外观/Worker 的委托与对应实现，不同时保留两套执行主体；保留运行数据、原 key 和接口。无数据库结构变化时不执行降库，已经创建的正式报告和执行事实不因代码回退删除。

前端类型和治理/测试资产页面拆分作为独立后续计划，不与本轮 tasks 拆分混合实施。
