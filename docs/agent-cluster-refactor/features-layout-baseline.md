# Features 目录迁移基线

核对时间：2026-10-29（Asia/Shanghai）

本记录在 `app/platform/` 与 `app/orchestration/tasks/` 迁移前生成。工作区本来就含大量未提交的重构修改；迁移前 `git status --short` 共 519 行，包含新增、修改和删除项。特别是 `backend/alembic/versions/0001_initial_schema.py` 已有预存修改，本轮将其视为用户数据，不会改动。

| 检查项 | 迁移前实测 |
|---|---:|
| FastAPI OpenAPI 路径 | 269 |
| OpenAPI method/path 组合 | 418 |
| OpenAPI raw schema SHA-256（基线采样） | `341349618097421d2fcbd87b83d791fb36495861ec3e338dc4e03fa21a0e3344` |
| OpenAPI 稳定 schema SHA-256 | `61efb84ca7b41b413e5988b6fd814c07772a0bfd00d1333d22760e9269bf53e7` |
| 已导入 ORM 表 | 112 |
| ORM metadata 结构 SHA-256 | `bded2fc08f414a439eef9945924151435ee84cc836686c211465ef70ca0a99bf` |
| pytest 收集 | 1049 tests |

基线导入了 `app.core.models`、agents/MCP/skills/tools models 和任务 models。API fingerprint 基于 `create_app().openapi()`；稳定 fingerprint 在 canonical JSON 中剔除 FastAPI 对同一个多方法动态 Mock 路由随机生成的 `operationId` 后计算。实测同一源代码的原始 OpenAPI hash 会因该 `operationId` 随机变化（出现过 `patch`、`delete` 等值），因此原始 hash 仅记录基线采样，不能单独用于回归判断。迁移前后的 schema JSON 逐字段 diff 只有该路由七个方法的 `operationId` 七处不同；paths、methods、参数、请求/响应 schema、状态码及其余组件完全相同，剔除 `operationId` 后 schema 相等，稳定 hash 均为上表值。ORM fingerprint 含表名、列名/类型/nullability/主键/server default、约束和索引。完整临时快照保存在 `/private/tmp/features-layout-baseline.json`，迁移前工作区状态保存在 `/private/tmp/features-layout-baseline-status.txt`；这些临时文件仅用于本轮对照，不是项目交付物。

基线 pytest 收集需显式设置 `TEST_POSTGRES_PASSWORD`。使用仅用于收集的值 `baseline-only`，未连接数据库。收集输出中的已有 Pydantic 字段命名和 mock 路由重复 operation ID 警告也已记录在临时基线输出。
