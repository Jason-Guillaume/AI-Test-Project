# 数据库迁移验收报告

日期：2026-11-16

## 执行范围与结果

| 项目 | 结果 |
|---|---|
| Alembic revision 唯一性 | 通过；head 为 `0086`，history 可完整遍历 |
| ORM/Alembic 模型注册 | 通过；187张模型表已注册，含两张生命周期表 |
| 新增索引迁移 | 已编写 `0086`，并通过临时 SQLite 上 upgrade→downgrade→upgrade 检查 |
| PostgreSQL 隔离库迁移回归 | 通过：4项迁移专项测试；含重复升级、0086降级/再升级及旧 Jenkins 0082 stamp 兼容 |
| 本机开发库迁移 | 已从0081升级至0086；PostgreSQL事务DDL成功 |
| 生产库迁移 | 未运行 |
| DROP TABLE / 历史数据清理 | 未执行 |

## 迁移链检查

`0081 → 0082 → 0083 → 0084 → 0085 → 0086` 为单一链。上游提交 `1f466ba` 已将 Jenkins 迁移从冲突的 `0082` 调整到 `0085` 并补兼容逻辑；本轮不改历史迁移。`0086` 只移除 `security_execution.test_run_id` 上的重复索引，规范索引为 `ix_security_execution_test_run_id`。

迁移防护会核对同名索引确为非唯一 `test_run_id` 索引；定义不符时中止。downgrade 会恢复旧名索引。普通索引 DDL 位于 Alembic 事务中，会短暂持有 PostgreSQL 表锁；应选低流量时段并观察锁等待。

## PostgreSQL 实库验收证据

本地 `testplatform_dev` 已升级至0086并只读复核：物理表190张（应用表189张），ORM表187张，DB-only为 `model_global_migration_audit` 与 `td_sandbox_task`，无 ORM-only 表；两个新增表均为空。`api_response` 保持131行，131行均有 response_key 且 status_code 未空；两个 timeout 超限计数均为0；automation_execution为空、config回填候选为0。FK约束全部 validated，invalid indexes为0，规范 test_run_id 索引仅一条。

升级前已采集两类 timeout 超限行数，均为0；因此本次没有触发不可逆的超时归一化。重复 Jenkins queue/build 字段在旧库中不存在，automation_execution为0行；迁移安全检查通过。

生产库未迁移，未在真实数据规模上量测索引查询计划；开发库表较小，查询计划可能合理选择顺序扫描。另有一次完整后端回归结果记录在 [`database_regression_report.md`](database_regression_report.md)；该套件未全绿，未通过项需要单独排查。
