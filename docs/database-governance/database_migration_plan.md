# 数据库迁移计划与执行状态

> 回滚更新（2026-11-16）：当前迁移链从 `0086` 前进到 `0087_restore_yunxiao_only_automation`。本节以下内容记录数据库治理任务完成时的 `0086` 快照；`0087` 保留 `0085`/`0086` 历史并清除已确认为空的 Jenkins 专属结构，保留云效执行历史、报告和通用接入关联。

更新时间：2026-11-16。P1/P2审计文档保留了2026-11-13的物理库采样快照。

## 当前迁移图

当前 `develop` 工作区的 Alembic 链为单一路径：

```text
0081 → 0082 API response keys → 0083 test-case import batch → 0084 organization recycle bin
     → 0085 Jenkins provider → 0086 security_execution index deduplication
```

`0082` 重复 revision 已由已合入的上游提交 `1f466ba` 修复：Jenkins 迁移现由 `0085` 承接，并覆盖旧 Jenkins `0082` stamp 的兼容形态。本轮没有编辑已发布的历史迁移文件。当前 `alembic heads` 为单一 head `0086`，历史链可遍历。

Alembic 目标 metadata 已注册生命周期模型；导入全部模型后有 **187 张表**，包含 `recycle_bin_item` 和 `data_lifecycle_audit_event`。

## P3：重复索引去重

新增 `0086` 迁移，保留 `ix_security_execution_test_run_id`，删除重复的 `ix_security_execution_run`。迁移仅处理 `security_execution(test_run_id)` 上的非唯一索引；如果同名索引定义不符，会中止迁移。若规范索引缺失，会先补建。降级会恢复旧索引名。

此批次不改表、行数据、外键或 API。使用事务内普通 `CREATE/DROP INDEX`，不是 `CONCURRENTLY`。本地开发库已应用并通过 PostgreSQL catalog 复核，规范索引只留一条；生产库未升级。

## P4：数据库实际升级前置检查

2026-11-16 已对本机 `testplatform_dev` 完成预检并升级至 `0086`。升级前为0081、188张物理表；升级后为190张物理表（189张应用表），无表删除。timeout超限影响0行；api_response有131行且 status_code 非空；automation_execution有0行，integration_config回填候选0。新增的两张表升级后均为空。

应用 `0085` 前在目标库只读核对以下会被规范化的数据量，并留存原值/备份；本地库结果均为0：

```sql
SELECT count(*) AS affected_rows
FROM automation_integration_config
WHERE default_timeout_seconds > 10800;

SELECT count(*) AS affected_rows
FROM automation_project
WHERE timeout_seconds > 10800;
```

`0085` 会把上述超限值改为 `10800`；本次没有触发这两项改写。automation_execution当前为空，integration_config回填候选为0；Jenkins queue/build列在升级前不存在，因此没有既有标识可重复。隔离 PostgreSQL 专项迁移测试4项通过，包括0086降级恢复旧索引并再次升级。不得直接把本报告当作生产放行。

## 预计表数量

| 状态 | 应用表 | 含 Alembic 表的物理表 | 说明 |
|---|---:|---:|---|
| 2026-11-13采样 | 187 | 188 | 物理库版本0081 |
| 2026-11-16升级后实测 | 189 | 190 | 物理库版本0086；DB-only两张表保留 |
| P3索引迁移净变化 | 0 | 0 | 只减少一条冗余索引 |

表数增长来自代码已有的导入批次审计表和 Jenkins 独立密文表，不是本次压缩动作。没有可证明无损的合并/删除候选，因此预计表数不减少。
