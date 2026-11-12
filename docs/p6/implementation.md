# P6 审计与实施设计

## 基线与 P5
当前工作分支 feature/case-generation-closed-loop，HEAD aa46bf1；本地 develop / origin/develop 为 f64ebd2，后者尚不含 9731f70、aa46bf1。保留现有未提交的 P5 验收代码及 UI 修改，不擅自合并 develop 或覆盖工作区。0047→0048→0049 构成线性迁移链；P5 使用独立 PostgreSQL 和本地 LLM stub 验收。

## 同步链路
POST case-generation-batches → GenerationService.start → generate_case_suite → LangGraph 顺序模块工具调用 → Supervisor Review → persist。所有模块结束后才保存批次，HTTP 长时间占用，重启丢失未保存结果。regenerate 同样同步。现有人工审核、质量检查与幂等入库保持。

## 兼容的持久化 Fan-out / Fan-in
沿用 Task / TaskRun / TaskWorkItem / TaskAttempt / TaskWorkItemDependency，不新增队列。现有租约属于 Run，不在同一 Run 上并行覆盖 lease_owner。一个生成 Task 内，每个模块是一个独立 Run + WorkItem；最后编号的协调 Run 仅执行 Supervisor Review，通过已有跨 Run 工作项依赖等待所有模块进入终态。批次唯一关联协调 Run；所有 Run 输入保存 batch_id、受控 Agent 配置快照和资源策略。模块独立 Session、租约、心跳、代次和持久化结果。TaskWorker 使用有界执行池运行已从数据库领取的工作；数据库仍是唯一调度事实源。

创建事务内原子写 Task、所有 Run、工作项、依赖、批次与 CREATE 审计。按用户+幂等键唯一约束复用任务，摘要不同返回 409。项目锁仅用于提交短事务和额度检查，不跨模型调用。模型配置版本、Agent / Skill / knowledge 快照不向前端返回完整指令或凭据。

## 状态
公共 TaskRun 枚举保持：QUEUED / RUNNING / SUCCEEDED / SUCCEEDED_WITH_ISSUES / FAILED / CANCEL_REQUESTED / CANCELLED。批次映射 SUCCEEDED→COMPLETED、SUCCEEDED_WITH_ISSUES→PARTIAL_FAILED，其余同名。每个模块完成即保存草稿和工作项结果；最终 Review 统一汇总。协调 Run 等待模块时状态表示整体生成进度。

## 恢复、取消与重试
沿用现有 Run 租约和 heartbeat 恢复未完成模块；写回前锁 Run 并验证 owner、attempt generation、attempt status、租约有效性。草稿用 work_item_id + ordinal 唯一约束，成功结果与终态同事务提交。失效执行者丢弃迟到结果。模型调用前结束数据库事务。取消原子标记所有子 Run：待执行直接取消，已执行在安全边界保留结果后取消；不删除草稿。Review 等待所有模块终态。仅失败工作项原地重新排队、增加尝试上限，成功工作项和人工审核草稿不变；Review 可单独重试。崩溃恢复上限耗尽转失败并继续聚合。

## API 与前端
新增 POST projects/{id}/case-generation-tasks（202）、GET batches/{id}/task、POST batches/{id}/cancel、POST batches/{id}/retry。旧 POST batches 和 regenerate 保持同步兼容，文档标记逐步废弃；异步批次禁止通过旧 regenerate 重跑。工作台切换到异步提交，React Query 轮询批次与任务，终态停止；历史批次和 localStorage 恢复任务，继续复用所有审核编辑入库组件。

## 资源与验证
统一调度控制行限制全局运行并发；配置 Worker 槽位、生成单项目/用户活跃额度、单批次模块并发、超时、重试退避、输出 Token 预算。模型超时/输出上限以已授权模型配置为基础，再应用生成策略上限。禁止测试访问真实模型，使用现有隔离数据库和可控替身，按 P6 阶段定向回归，最后全量后端、前端和 Playwright 验收。

## 实现细节与事务边界

- 创建 API 先取得用户和项目短锁，检查当前成员/组织模型权限、方向与范围，冻结 Agent、Skill、knowledge 和模型配置摘要；原子提交 Task、模块 Run、协调 Run、WorkItem、依赖、Batch 和 CREATE 审计。HTTP 不构建 Provider、不调用模型。
- 每个模块的 Run 是该 Task 的内部编排分支，不表示用户发起了新一轮生成；最高 run_number 始终为协调 Run。协调 Run 的输入保存同一 batch_id，批次的 task_run_id 唯一引用该 Run。通用任务命令和消息对 CASE_GENERATION 返回明确冲突，避免误走测试执行或目标重定向流程。
- TaskWorker 的有界执行池只执行已提交、已租约领取的工作项。每个线程在 _run_claimed 创建独立 Session；心跳仍使用独立 Session。槽位取 TASK_WORKER_CONCURRENCY 与 DB_POOL_SIZE/2 的较小值。
- 领取沿用 task_scheduler_control 的数据库锁和全局并发额度。同 Task 的活跃租约还受模块并发快照约束。CASE_REVIEW 依赖允许模块成功、失败、取消三类终态；其他业务工作项依赖契约完全保持。
- 外部请求前重新检查授权、版本、取消和租约；提交知识检索/配置读取事务，再短锁批次预留 token。外部 HTTP 期间没有数据库事务、连接占用或行锁。
- Token 采用保守预留：输入 UTF-8 字节上界（另加消息开销）+ 配置内输出上限；失败请求也不退还未知消耗，避免恢复/重试绕过预算。各尝试预留在 TaskAttempt.checkpoint_json，实际 usage 单独记录。此为保守资源保护，不替代供应商计费账本。
- 写回先刷新 Session 缓存，按 batch→run 加锁，校验 lease_owner、未过期租约、attempt.status、work.status、lease_generation。草稿与模块成功结果同事务；重启发生在提交前则可重试，发生在提交后则不会再次领取成功工作项。
- 异步模块写回只重算待审核草稿质量，不改已接受/拒绝草稿。人工编辑和正式入库继续沿用原实现；单条入库冲突新增持久化失败原因。
- 过期生成租约仍由现有 recover_expired 入口处理，按相同锁序恢复，指数退避，有次数上限。通用任务恢复逻辑跳过 CASE_GENERATION，避免两条恢复路径同时修改同一 Run。
- 运行中的取消等待已发出的不可中断请求返回；成功内容照常持久化，未开始的模块和 Review 直接取消，最后汇总为 CANCELLED。Review 与模块重试均走同一持久化工作项，成功项不重跑。

## 公共状态映射

| 任务状态 | 批次状态 | 语义 |
| --- | --- | --- |
| QUEUED | QUEUED | 已持久化，尚未执行 |
| RUNNING | RUNNING | 模块执行、退避或等待 Review |
| SUCCEEDED | COMPLETED | 全部模块和 Review 成功 |
| SUCCEEDED_WITH_ISSUES | PARTIAL_FAILED | 至少一模块成功，但模块或 Review 有失败 |
| FAILED | FAILED | 全部模块失败或不可恢复 |
| CANCEL_REQUESTED | CANCEL_REQUESTED | 等待在途模型请求安全返回 |
| CANCELLED | CANCELLED | 全部工作项已安全停止 |

任务 status 是聚合状态。单模块 Run 可以 FAILED，而父 Task 为 RUNNING 或 SUCCEEDED_WITH_ISSUES。Review 工作项本身在所有模块失败时成功产出“全部失败”摘要，但整体 Task / Batch 仍 FAILED。

## 后端接口与兼容

| 方法与路径（均在 /api/v1） | 返回与控制 |
| --- | --- |
| POST /projects/{id}/case-generation-tasks | 202，GenerationBatchResponse 新增 task_id / task_run_id；必填 request_key（用户维度、内容摘要匹配） |
| GET /case-generation-batches/{id} | 继续返回现有草稿详情，新状态对旧批次无影响 |
| GET /case-generation-batches/{id}/task | task_id、run_id、batch_id、状态、completed/total、模块身份/版本/状态/起止时间/耗时/usage/重试/脱敏错误/trace_id、任务事件 |
| POST /case-generation-batches/{id}/cancel | 幂等协作取消，保留草稿 |
| POST /case-generation-batches/{id}/retry | 仅终态失败项；Review 可独立重试；并发额度与总尝试限制仍生效 |
| POST /projects/{id}/case-generation-batches | 原同步响应和调用约定保持；OpenAPI 标记 deprecated |
| POST /case-generation-batches/{id}/regenerate | 仅旧同步批次兼容；异步批次返回 409，引导 retry |

原草稿 PATCH、accept、reject、reopen、批量 review、audits 和正式用例追溯接口保持。旧接口本轮不删除；下一次破坏性版本前统计旧调用方并完成迁移，再单独公告移除。不把旧接口静默改成 202，避免同步调用方误用空草稿响应。

## 前端

现有 GenerationWorkbench 改用异步 API。提交成功即显示任务 ID；同一提交意图复用幂等键，终态后可明确“新建生成任务”。BatchDetail 使用 React Query 每 1.5 秒读取批次与任务，后台标签页继续轮询，终态停止。关闭浏览器不会发取消请求。localStorage 只保存账号+项目+方向范围内的批次引用，刷新后重新鉴权读取；历史列表始终可重新打开任务。保留草稿编辑、质量提示、逐条/批量审核、拒绝恢复、入库失败原因、批次审计。新增模块起止时间和任务事件时间线。

## 0050 迁移

在 0049 后追加 0050，不建新队列或批次表：

- case_generation_batch.task_run_id：可空、唯一，引用协调 TaskRun。
- case_draft.work_item_id / result_ordinal：可空，联合唯一约束防止模块结果重复写入。
- 外键为可延迟约束：阻止孤立删任务，同时允许原有项目整体级联删除。
- 旧批次与草稿新增字段均为 NULL，无需重生成。0049 审计、原始 payload、已审核状态与正式用例保持。
- 部署先停止旧 Worker、备份并执行 `alembic upgrade head`，再滚动启用新版本；旧版本代码不能识别新工作项，禁止混部消费。
- 回退先停止/清空新增生成任务的在途执行，再运行 `alembic downgrade 0049`；只移除关联与约束，不删除生成草稿、审计或正式用例。旧代码无法恢复异步任务，回退前必须记录/收敛这些运行。

## 资源默认值与运维

| 配置 | 默认 | 依据与限制 |
| --- | --- | --- |
| TASK_WORKER_CONCURRENCY | 2 | 与现有 ASR Worker 两槽位同量级；另受主库 pool_size/2 和数据库全局闸门约束 |
| CASE_GENERATION_MODULE_CONCURRENCY | 2 | 双模块并行已通过屏障测试和真实 HTTP 桩重叠时间验收 |
| CASE_GENERATION_PROJECT_CONCURRENCY | 2 | 单项目双任务及超额拒绝已验收 |
| CASE_GENERATION_USER_CONCURRENCY | 2 | 创建和手动重试均检查，按原任务发起人计数 |
| CASE_GENERATION_MODULE_TIMEOUT_SECONDS | 120 | 在现有模型默认 60 秒基础上提供模块边界余量，实际模型请求取配置 timeout 与该值较小者 |
| CASE_GENERATION_MAX_ATTEMPTS | 3 | 沿用现有 WorkItem 默认上限 |
| CASE_GENERATION_TOTAL_ATTEMPTS | 6 | 含手动重试；最多容纳两轮默认自动重试预算 |
| CASE_GENERATION_RETRY_SECONDS | 30 | 与现有任务模型重试起始退避一致，指数增长 |
| CASE_GENERATION_TOKEN_BUDGET | 65536 | 可配置的保守任务预留上限；单次输出仍受模型 max_tokens 和分配预算约束 |

现有 task_scheduler_control.max_concurrent_runs 默认 1，本轮不擅自扩大所有业务的全局额度。生产需要并行时，由运维在现有控制行调高额度（例如 2），同时检查模型供应商额度与连接池。E2E 只在专属隔离库设置为 2。Stub 测试验证正确性和资源边界，不能代替真实供应商生产压测。

## 已知限制与技术债

1. 原同步接口为兼容继续存在，旧调用方仍可能占用长 HTTP；本轮工作台已经完全使用异步入口。
2. 数据库全局并发默认 1；并行能力不会绕过这一保护。未调高全局额度时，模块安全串行执行。
3. 模型供应商的在途不可中断请求无法立即释放网络资源。任务/Attempt 截止可由租约恢复入口收敛，失效结果被拒绝；网络线程仍等待请求返回或 HTTP timeout，取消不强杀请求。
4. 同一个 Task 内的多个 Run 在通用任务历史中可见；它们是模块分支。未来可增加分组展示，本轮使用生成工作台统一控制，防止误走测试执行命令。
5. 保守 token 预留可能拒绝实际仍有余量的请求；未知消耗不退还。需用真实模型计费/分词数据进一步校准默认预算。
6. 每次轮询仍进行一次过期租约查询，规模更大时应专项评估索引与批量恢复策略；本轮不另建调度服务或 SSE。
7. 本地 develop 与跟踪引用尚未包含 P5 审核闭环提交；当前改动基于其后代工作分支，未自动提交或合并到 develop。

## 联合验收追加：0051 执行身份字段

开发期间共享工作区另行加入 0051_runtime_execution_identity（用户已明确要求纳入联合验收）。该迁移位于 0050 后，扩展 TaskRun.execution_root_run_id / trace_id / deadline_at、TaskAttempt.deadline_at 和 TaskAgentInstance 的修订/父实例引用。执行根使用 (root_id, task_id) 复合外键阻止跨 Task 拼接；已有生成批次可回填到协调 Run，历史 Trace / deadline 保持 NULL，不伪造执行证据。通用 create_run 生成 Trace 身份，公共序列化增加相应字段。

0051 字段均为可空增量，与 P6 原有租约、代次、快照、取消和重试接口兼容。P6 新生成任务在创建事务中为全部模块及协调 Run 写入同一 execution_root_run_id 和持久化 Trace ID；Langfuse 关闭时也能关联，开启时沿用该 ID 关联真实 span。历史未知 Trace 保持 NULL。联合底座同时加入任务总截止与 Attempt 截止：领取时限定模块执行边界，续租不能越过截止，排队超时由恢复入口直接收敛；在途请求仍不强杀，失效结果被 fencing 校验拒绝。联合迁移测试验证回填、跨任务约束、可空历史身份和 downgrade 0050 保留原 Task/Batch。部署迁移目标更新为 head（当前 0051），完整回退到 0049 会先按 Alembic 依次回退 0051 和 0050。


### 冻结版联合底座补充

按用户明确要求，纳入另一聊天已完成的 P6 运行底座改动：

- 沿用 TaskAgentInstance 作为 agent_run_id，为每个模块建立独立 AgentSession，记录 Supervisor 父实例和可用的 AgentDefinitionRevision 引用；不另建 Agent 执行实体。
- 新增 CASE_GENERATION_TASK_TIMEOUT_SECONDS（默认 1800 秒，可配置），作为含排队的任务总截止；模块 Attempt 使用更短截止。heartbeat / complete / fail 使用一致的 fencing 校验，失效或终态执行不能被旧心跳复活。
- 依赖就绪条件进入 SQL 筛选，避免前 20 个不可执行工作项导致后续就绪模块饥饿。
- 预算从 Attempt 单条预留进一步收敛为逐模型调用预留与结算；有可信 usage 时按实际消耗，未知供应商消耗保留上界。失败调用也记录安全的使用量与错误类型。
- 0051 历史执行根按已有批次证据回填；后续代码已冻结，统一测试以 verification-snapshot.json 为准。

本轮联合验收仅覆盖这些与 P6 可靠性直接相关的改动，不代表 P8/P9/P10 的其余功能已研发或验收完成。
