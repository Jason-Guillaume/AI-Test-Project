# 数据库重复与收敛分析（P1）

> 物理索引证据来自2026-11-13采样；本轮0086已在开发库执行，2026-11-16复核只剩规范索引 `ix_security_execution_test_run_id`。

## 结论

- 没有发现可凭字段相似度直接判为重复业务实体的一组表。
- **建议合并表：0 组；建议 JSONB 迁移表：0 张；已证明可删除表：0 张。** 当前阶段的结论是保持核心实体独立，先处理迁移版本链、ORM 注册缺口和重复索引。
- 有 2 张物理库表没有 ORM 模型；有 2 张 ORM 表当前 0081 数据库尚未创建。它们不是“重复表”，应按迁移/历史保留评估。
- 一个被 PostgreSQL catalog 证实的完全重复索引：`security_execution(test_run_id)` 两个 B-tree 索引。

## 已证实的物理冗余

### `security_execution` 重复索引（低风险候选）

审计时，`backend/app/features/security_testing/models/execution.py` 同时声明显式 `Index("ix_security_execution_run", "test_run_id")`，又由 `test_run_id = Column(..., index=True)` 触发默认索引。实际 PostgreSQL catalog 显示两者均为 `USING btree (test_run_id)`，定义相同。

处理状态：ORM 已移除显式声明；0086保留 `ix_security_execution_test_run_id`、删除冗余名，并实现降级恢复。该项不改变表数、行数据、FK、查询/API语义；物理应用和迁移期间锁时间待 PostgreSQL 恢复后验收。

## 模块级重复候选审查

| 模块/表组 | 相似处 | 不同生命周期/约束证据 | P2 结论 |
|---|---|---|---|
| ASR `asr_review_audit` / `asr_speaker_review_audit` | 均含 reviewer、版本/状态、时间 | 分别 FK 到 `asr_diff_block` 与 `asr_speaker_assignment`；转写审计保存确认文本/参考样本标记，说话人审计保存 speaker 归属；父实体及审计负载不同 | 保留；统一表会把强 FK 改成多态/可空关系，当前无共同查询证据 |
| ASR `asr_work_item` / `asr_processing_work_item` / `asr_suggestion_job` / `asr_content_review_job` | 都有状态、尝试或租约 | 分别处理模型运行、说话人/媒体处理、建议生成、内容评审；幂等键、阶段和失败重试合同不同 | 保留独立队列与恢复边界 |
| 测试管理断言/前置条件/数据 | 都是用例输入子实体 | 各有自身字段、排序/执行语义、CRUD/审核与回收站要求，测试数据不能替代断言 | 保留；不收进单一 JSON |
| 业务 `BusinessPrecondition`/`BusinessRule`/`BusinessState`/`BusinessVariableRef` | 都约束流程/动作 | 一个是执行条件，一个是规则实体/状态模型/变量引用，外键及执行引擎语义不同 | 保留 |
| 业务 `FlowExecution` / `ActionExecution` | 都是执行记录并含状态/时间 | Action 是 Flow 下按序子执行，包含 binding、上下文快照；父子查询、重试和幂等边界不同 | 保留父子实体 |
| 测试数据 `FixtureExecution` / `ProviderExecution` / `DataExecution` | 都记录执行 | Fixture 依赖图/清理、Provider 调用、Data 生成与池租约的状态和输出边界不同 | 保留；统一执行表会增加多态 FK 并弱化清理安全性 |
| 安全 `SecurityFinding` / `SecurityScanFinding` / `SecurityScanEvent` | 都属于安全结果 | 自研安全用例结果、ZAP 任务事件及每次扫描命中来源/去重关系分别管理；事件是审计时间线，不是 Finding | 保持安全域隔离 |
| Agent `RuntimeCallFact` / `RuntimeEventFact` / `RuntimeTraceProjection` | 都关联任务运行/trace | 调用事实用于 token/cost，事件事实表示运行事件，投影为查询读取模型；保留来源、投影及 Outbox 语义 | 保留 |
| 模型中心 `model_configuration` / `asr_connection` / `asr_parameter_set` 与 `model_resource`/revision/profile/credential | 都可配置模型/参数 | 0034 建立统一 ModelResource 并保留 legacy binding；服务仍同步兼容旧实体；Credential 单独密文表且应独立隔离 | 先迁移调用链与历史映射，不删旧表、不合并凭据 |

## 历史/辅助表处理

- `test_scope_api_backfill`：0047 upgrade 记录哪些 `api_id` 由迁移回填，downgrade 读取该表后才清空这些值。**必须保留**到不再支持该 downgrade 且其数据保留得到决定。
- `test_scope_migration_check`：保存迁移前后计数；无运行时代码命中。暂留为迁移审计证据，待回滚/审计保留要求确认。
- `model_global_migration_audit`：0046 历史迁移写入旧资源状态与处理决策；当前无 ORM。不能因为没有运行时代码就删。
- `td_sandbox_task`：0009 文档明确为 Provider 白名单验证的测试 sandbox。确认测试数据库用途、fixture 和数据后再评估。
- `alembic_version` 是迁移基础设施，不纳入业务压缩。

## JSON/JSONB评估

对 187 张 ORM 表共扫描到 184 个 JSON 类型字段（103 张表）。执行快照、原始/规范化 ASR 输出、结果、配置参数、事件负载和报告/分析结果均承担审计、恢复或外部协议快照用途；这类字段不能因“结构灵活”而转成单一大 JSONB。

未找到有证据支持把身份/权限、密钥、执行历史、强外键子实体迁入 JSONB 的对象。配置中心已有 `ModelRevision`、`ModelParameterProfile` 与独立 `ModelCredential` 边界；建议保持关系型资源/版本/密钥及其约束，灵活配置仍只留在相应配置快照/参数字段。

## 可删表结论

本次只读 catalog 未读取行数、内容或跨环境状态；外部消费者和部署历史也不可由本工作区证明。因此 D 类“可删除”当前为 **0**。`model_global_migration_audit`、`td_sandbox_task` 和两个测试范围迁移辅助表均列为 E 暂保留，不能直接 DROP。
