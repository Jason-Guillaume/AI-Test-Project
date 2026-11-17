# 数据库迁移验收

## 0084 定向矩阵

测试文件：`backend/tests/test_57_organization_recycle_bin_migration.py`。

| 方言与场景 | 结果 | 说明 |
|---|---:|---|
| SQLite：四列均缺失 | 通过 | 逐项添加并创建外键 |
| SQLite：每个软删除列单独预存 | 通过 | 其它缺失列仍会补齐 |
| SQLite：全部列已存在、外键缺失 | 通过 | 补建一个正确外键 |
| SQLite：全部列和外键已存在 | 通过 | 不创建重复外键 |
| PostgreSQL：四列均缺失 | 通过 | 从 0083 明确升级到 0084 |
| PostgreSQL：部分列和已有值、外键缺失 | 通过 | 补齐结构并保留删除时间、操作者、原因 |
| 重复升级、downgrade 后再升级 | 通过 | 0084 重复运行无重复对象；downgrade 不删字段和值 |

结果：**9 passed**（7 个 SQLite 组合 + 2 个 PostgreSQL scratch 数据库测试）。PostgreSQL 测试只创建和删除唯一命名的临时库，没有操作开发库或生产库。

## 全新 base → head 与旧历史分支

全新数据库 base → head 目前无法执行，不是 0084 DDL 失败，而是 Alembic 在解析目标 `head` 时立即发现两个 `0082` 声明，报告 heads 为 `0082`、`0084`。因此场景 A 的完整链路尚未被证明；针对 0084 的 PostgreSQL 测试从 0083 升级至 0084，SQLite 测试直接在各历史列组合上执行该 revision。

当前仓库要求保留已发布迁移；本轮没有改写 `0082_api_response_keys.py`、`0082_automation_jenkins_provider.py`、`0083_test_case_excel_import.py` 或 `0001_initial_schema.py`。处理同名 0082 需要先明确已部署库中 `alembic_version=0082` 对应的实际 schema，再制定独立向前兼容方案。

全后端运行结果为 **648 passed、604 errors**。需要 session PostgreSQL 数据库的用例在 fixture 的 `upgrade head` 初始化阶段失败，错误均呈现同一 MultipleHeads 问题；这些错误不能记作产品功能通过或失败。无数据库 fixture 的测试仍有通过项。
