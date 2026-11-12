# P8 Trace 投影可靠性收口

## 现有实现复用

PostgreSQL 的 `TaskRun`、`TaskAttempt`、`RuntimeCallFact`、`RuntimeEventFact` 继续作为业务运行事实；Langfuse 继续持有 observation 正文。Trace 页面原有的任务时间线和项目权限过滤保持不变。本阶段不新增第二份 prompt、响应或工具参数存储。

## Outbox 与状态

新增 `RuntimeTraceProjection` outbox。它只记录来源类型/键、Trace/span 关联、任务关联和投递状态，不存储原始 observation 正文。模型调用、工具/RAG/上下文/Skill 事件和 Agent Attempt 的 outbox 行与来源事实在同一 PostgreSQL 事务中创建；`0061_runtime_trace_projection` 同时为有 trace_id 的历史事实建立待投影索引。

状态为 `PENDING`、`RETRYING`、`SUCCEEDED`、`FAILED`。Worker 用 `FOR UPDATE SKIP LOCKED` 领取任务，短事务写租约，释放数据库连接后调用 Langfuse，再以新事务更新回执。失败采用指数退避，最多自动尝试 8 次；租约到期的 `RETRYING` 会重新领取。Langfuse 没有配置或不可达只影响投影，不改变 Agent 任务状态。

恢复 observation 只发送业务关联、事件名称、状态、耗时、token/成本数值及已脱敏的白名单 metadata。若来源事实已有 Langfuse span ID，会先通过 observations API 核对；重试也会按稳定 `runtime_projection_key` 核对。读取侧可能存在延迟，歧义投递会等待 15 分钟再尝试，避免盲目重发。观测 API 不可用时记录失败状态，不会假称投影完成。

Langfuse Python SDK v3/v4/v5 的 observation ID 由 SDK/OpenTelemetry 管理，不能由本项目指定自定义 observation ID；因此这里使用数据库唯一键和远端回查降低重复，不宣称外部服务具备数学意义上的 exactly-once。Langfuse 的 `flush()` 成功表示数据已投递到 API，不等同于读 API 已立即可见。

## 查询与补偿

- `GET /api/v1/task-runs/{run_id}/trace` 现在返回整体投影状态、各状态数量、最近成功时间和当前页事件的投影状态。
- `POST /api/v1/task-runs/{run_id}/trace/replay` 按既有项目写权限登记遗漏的历史事实，并重排失败记录；不修改 TaskRun 状态。
- Trace 时间线 UI 展示 Langfuse 投影状态和失败重放操作。

## 数据库与测试

新增 Alembic `0061_runtime_trace_projection`，包含投影状态/租约字段、唯一约束、到期扫描索引和历史事实回填。回滚只移除 outbox，不改写原始运行事实。

`tests/test_62_trace_projection.py`：**4 passed**。覆盖稳定键去重、敏感字段丢弃、投递成功、外部失败后退避、任务事实状态不受 Langfuse 故障影响、Worker 崩溃后的远端回查去重，以及 Trace API 返回 Outbox 总体/单事实状态。

## 部署限制

没有接入真实 Langfuse 凭据/实例做端到端网络验收。Outbox 使用 Langfuse observations 查询接口进行回查；部署环境需要提供兼容的 observations API。若当前服务端不支持该读取接口，记录会安全地进入 `FAILED`，前端可显示并由有写权限用户重放，但操作方应先确认服务端兼容性。
