# 数据库治理回归报告

日期：2026-11-16

## 通过项

| 检查 | 结果 |
|---|---|
| Alembic migration graph 单 head 与唯一 revision | `1 passed`；head `0086` |
| 隔离 PostgreSQL 迁移专项（最终代码） | `4 passed`；含从 base 升级、重复 upgrade、0086降级/再升级与旧 Jenkins 0082 stamp 兼容 |
| ORM metadata 注册 | 通过；187张表，含两张生命周期表 |
| 0086 upgrade/downgrade/re-upgrade | 临时 SQLite与隔离 PostgreSQL验证通过；开发库实测只剩规范索引 |
| PostgreSQL约束/索引状态 | FK约束全部 validated；invalid indexes为0 |
| 前端单元测试 | `npm test`：44通过、0失败 |
| 前端生产构建 | `npm run build`：TypeScript与Vite构建通过 |

## 完整后端套件

完整 `pytest -q` 结果（在加入最后一条0086降级测试前）：**1254 passed, 9 failed, 6 errors**（1269项）。随后迁移专项使用最终代码重跑，4项全通过。完整套件失败项如下：

- 注册/组织权限：`test_02_auth_flow::test_register_creates_user_and_personal_organization`；`test_05_isolation.py` 有6项 setup error（普通注册用户创建组织返回403）。
- 用户/组织持久化：`test_06_persistence.py` 中4项失败。
- 用户回收站预览：`test_74_user_lifecycle::test_user_purge_preview_protects_project_and_org_references` 未返回测试期待的 `organization.owner_id` 依赖。
- 接口目录：`test_api_catalog::test_module_crud_two_level_and_default` 期待有子模块时返回409，实际返回204。
- `test_22_security_strategy` 的 downgrade 用例和 Jenkins discovery 用例在全量运行中失败；分别单独重跑后通过，表现为顺序相关或不稳定。

本次改动仅涉及 Alembic metadata 注册、安全执行索引声明/迁移和迁移断言，没有改组织权限、用户回收站或接口目录服务。除 migration/Jenkins 两项在全量运行中的不稳定表现外，其余失败看起来与本次 schema 变更无直接关联；完整套件仍未全绿，相关行为需要单独排查。

## 实库验收

`testplatform_dev` 已升级到0086：190张物理表、189张应用表；131条 `api_response` 均有 response_key；两个超时超限计数为0；automation_execution为空、关联回填候选为0；重复安全索引已去重。没有对生产库执行操作。

全量测试后发现14个带 `testplatform_test-*`、`testplatform_migration_*` 或 `testplatform_gate_*` 前缀的数据库，来源无法确认；没有删除它们。后续清理需先确认各库归属和用途。

## 本地 backend 状态

旧容器只包含到0085的 Alembic 代码，数据库升级后无法启动。完整镜像重建因 Debian apt 源网络不可达而失败；随后基于本地旧镜像补齐当前 Python requirements 和工作区 app/Alembic 代码，仅重建 backend，容器已恢复为 `healthy`。旧镜像保留为 `ai-test-project-backend:pre-0086` 回退标签。
