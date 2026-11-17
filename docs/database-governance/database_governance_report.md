# 数据库治理总报告

更新时间：2026-11-16。审计对象为当前工作区代码和本机开发数据库 `testplatform_dev`；未访问生产库。

## 结论

- ORM与 Alembic target metadata 均为 **187张表**。初次审计发现的生命周期模型注册缺口已修复。
- 开发库已从0081升级至0086。升级后 **190张物理表**（含 `alembic_version`），即189张应用表；DB-only表为 `model_global_migration_audit`、`td_sandbox_task`，无 ORM-only 表。
- P3重复索引已在开发库去重：`security_execution(test_run_id)` 从两条同定义索引降为一条规范索引。FK约束全部 validated，索引有效。
- 0085预检的 timeout 超限行数均为0；`api_response` 131行全部补有 response_key；automation_execution 为空、integration_config回填候选为0。两个新增表升级后均为空。
- 没有可有证据支持的表合并、JSONB收敛或删除组：合并0组、JSONB迁移候选0张、已证明可删除0张。没有执行 DROP TABLE 或数据清理。

## 表数量前后对比

| 指标 | 治理前实测（0081） | 治理后实测（0086） |
|---|---:|---:|
| ORM 表 | 187 | 187 |
| Alembic target metadata 表 | 185 | 187 |
| 应用物理表 | 187 | 189 |
| 含 `alembic_version` 的物理表 | 188 | 190 |
| DB-only表 | 2 | 2 |
| ORM-only表 | 2 | 0 |
| 表合并/删除 | 0 / 0 | 0 / 0 |

新增两张表分别是 `test_case_import_batch`（0083，测试管理+1）与 `automation_jenkins_credential`（0085，自动化中心+1）。其他模块数量不变；0086只移除一条索引。压缩没有靠牺牲实体边界或数据完整性减少表数。

## P1/P2 审计结论

- 每张 ORM 表均有逐表结构、模块归属、外键和代码依赖记录；完整结构快照见 [`database_inventory.md`](database_inventory.md)，其列差异细节采于迁移前0081。
- ASR、测试管理、业务执行、测试数据、安全/ZAP、Agent/任务、模型凭据等实体保留各自关系约束和生命周期；无证据支持合并。
- DB-only历史/测试表及迁移辅助表暂留；没有把“无运行时代码命中”当作可删除证明。
- 迁移冲突已由上游提交修复，当前 Alembic head 为0086；本轮未改历史迁移文件。

## P3/P4 验收状态

- 开发库升级至0086并完成表数、关键回填计数、约束有效性和索引定义核对。
- 隔离 PostgreSQL 迁移专项4项通过（含0086降级/再升级）；前端44项通过且生产构建通过。
- 后端全量回归：1254通过、9失败、6错误。组织/权限、用户回收站和接口目录测试仍有失败；安全迁移与 Jenkins 测试在全量运行中不稳定、单独重跑通过。详情及失败名见 [`database_regression_report.md`](database_regression_report.md)。
- 本地 backend 已基于当前代码恢复为 healthy；生产库未连接或迁移。

交付文档：[`迁移报告`](database_migration_report.md)、[`回归报告`](database_regression_report.md)、[`前后数量对比`](database_before_after_comparison.md)、[`数据迁移与回滚说明`](数据迁移与回滚说明.md)、[最终ER图](database_er_diagram.md)。
