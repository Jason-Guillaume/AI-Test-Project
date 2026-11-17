# 数据库合并方案（P2）

> 本方案结论仍有效；本轮P3代码与0086迁移已应用到本机开发库，物理索引复核通过。

## 决策

**本轮不提出表合并组（0 组）。** 逐表结构和代码依赖证据表明，重点模块中相似字段多为状态快照、租约或审计字段的复用；其父外键、重试/回滚边界、历史版本或查询负载不同。把它们并表会引入多态 FK、可空字段和类型分支，暂时没有代码证据证明收益能覆盖关系完整性损失。

| 候选范围 | 原表 | 目标表 | 结论 |
|---|---|---|---|
| ASR人工审核 | `asr_review_audit`, `asr_speaker_review_audit` | 无 | 审核主体和负载不同，保留 |
| ASR队列 | `asr_work_item`, `asr_processing_work_item`, `asr_suggestion_job`, `asr_content_review_job` | 无 | Worker恢复、阶段、幂等合同不同，保留 |
| 测试输入 | `test_assertion`, `test_case_precondition`, `test_case_data` | 无 | 输入语义、执行与编辑生命周期不同，保留 |
| 业务约束/执行 | `business_precondition`, `business_rule`, `business_state`, `business_variable_ref`, `flow_execution`, `action_execution` | 无 | 变量解析/前置条件/状态/父子执行不能等价替代，保留 |
| 测试数据执行 | `fixture_execution`, `provider_execution`, `data_execution` | 无 | 依赖解析、提供器调用、清理/租约边界不同，保留 |
| 安全/ZAP | `security_finding`, `security_scan_finding`, `security_scan_event` | 无 | 安全问题、扫描命中、事件审计实体隔离，保留 |
| Agent/任务事实 | `runtime_call_fact`, `runtime_event_fact`, `runtime_trace_projection` | 无 | 事实来源、投影及成本统计用途不同，保留 |
| 模型中心旧/新体系 | `model_configuration`, `asr_connection`, `asr_parameter_set`, `model_resource`, `model_revision`, `model_credential`, `model_parameter_profile`, `model_legacy_binding` | 无 | 0034 后仍存在双向兼容调用；先迁完调用链，独立密钥表必须保留 |

由于没有提出表合并，不存在可负责任给出的“合并目标 DDL、数据迁移 SQL、表数减少预估”。表的完整结构、索引、外键和代码引用逐项见 [`database_inventory.md`](database_inventory.md) 与 [`database_dependency_analysis.md`](database_dependency_analysis.md)。

## 已有结构优化建议（非表合并）

`security_execution` 的两个 `test_run_id` 普通索引在 PostgreSQL catalog 中定义完全相同。已保留 `ix_security_execution_test_run_id`、移除显式重复声明并新增可回滚的0086索引迁移；物理库应用后需再核验。本优化减少索引冗余，不减少表数。

## 表处理基线

| 类别 | 数量（ORM+物理库表名并集 190 张） | 本轮规则 |
|---|---:|---|
| A 必须独立保留 | 186 | 保持当前表及强关系 |
| B 可合并 | 0 | 无合并组 |
| C 可评估 JSONB 收敛 | 0 | 不改变 JSON/关系结构 |
| D 已证明可删除 | 0 | 没有数据/保留/外部依赖证据 |
| E 暂时保留 | 4 | 两张迁移辅助表、两张无 ORM 历史/测试表 |

物理数据库 188 张表（其中 1 张 `alembic_version`），全量 ORM 187 张表；两个集合有差异，不能将并集分类计数误认为某一环境的当前物理表数。
