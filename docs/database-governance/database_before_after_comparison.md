# 数据库治理前后对比

口径说明：治理前来自2026-11-13全量审计与0081物理库采样；治理后来自2026-11-16对同一本机 `testplatform_dev` 完成迁移后的只读复核。

| 指标 | 治理前实测（0081） | 治理后实测（0086） | 变化 |
|---|---:|---:|---:|
| 物理表总数（含 `alembic_version`） | 188 | 190 | +2 |
| 应用物理表 | 187 | 189 | +2 |
| ORM声明表 | 187 | 187 | 0 |
| Alembic target metadata 表 | 185 | 187 | +2 |
| DB-only表 | 2 | 2 | 0 |
| ORM-only表 | 2 | 0 | -2 |
| 物理数据库版本 | 0081 | 0086 | +5 revisions |
| `security_execution(test_run_id)` 同定义索引 | 2 | 1 | -1 |
| 业务表合并 / 删除 | 0 / 0 | 0 / 0 | 0 / 0 |

## 表数变化的解释

净增两张应用表来自既有迁移：`test_case_import_batch`（0083，测试管理+1）和 `automation_jenkins_credential`（0085，自动化中心+1）。升级后两表均为空。原有 DB-only `model_global_migration_audit`、`td_sandbox_task` 保留；ORM-only表已通过迁移创建，因此不再有 ORM-only 表。0086只去重索引，不改变表数。

本轮治理没有减少表数。结构已与 Alembic head 对齐，但完整后端回归有9项失败、6项错误，详见 [`database_regression_report.md`](database_regression_report.md)。
