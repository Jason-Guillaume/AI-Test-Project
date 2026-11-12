# Features 目录布局迁移交付记录

实施日期：2026-10-29（Asia/Shanghai）

## 实际迁移

| 原路径 | 新路径 |
|---|---|
| `backend/app/features/users/` | `backend/app/platform/users/` |
| `backend/app/features/organizations/` | `backend/app/platform/organizations/` |
| `backend/app/features/projects/` | `backend/app/platform/projects/` |
| `backend/app/features/environment_configuration/` | `backend/app/platform/environment_configuration/` |
| `backend/app/features/model_configuration/` | `backend/app/platform/model_configuration/` |
| `backend/app/features/notifications/` | `backend/app/platform/notifications/` |
| `backend/app/features/agent_governance/` | `backend/app/platform/agent_governance/` |
| `backend/app/features/tasks/` | `backend/app/orchestration/tasks/` |

`app/features/` 当前保留 api_catalog、business、mock_management、security_testing、test_data、test_management、web_ui、defects、reports、dashboard 十个业务模块。未建立旧路径转发包。

更新了 `main.py`、Alembic 环境、backend 测试、seed 脚本和领域调用中的导入。全仓 backend 源码/测试/scripts/Alembic runtime 搜索不再发现旧 Python 包路径；历史迁移文件未编辑。

Alembic 环境显式导入平台环境和通知模型、所有业务模型包、编排任务模型及 business 的 `ActionExecution` / `FlowExecution`。隔离进程按同一发现清单得到 112 张唯一表，与迁移前 metadata 指纹一致；本次没有向 `app.core.models` 加入领域模型，也没有发现重复实体注册。

## tasks 与 Web UI 依赖调整

`web_ui.services.session_service` 不再导入编排任务模型。`app/orchestration/tasks/services/web_session_binding.py` 提供 `validate_task_web_session_binding`，任务启动浏览器时通过 Web UI 的 `TaskBindingValidator` 窄回调注入校验。缺少校验回调的任务绑定请求会以原有隐藏资源语义返回 404。

Web UI 仍先校验项目写权限并解析项目环境；任务校验仍检查项目归属、`WEB_AUTHORING` 类型、运行状态、批准环境以及指定参与者属于同一运行且角色为 `UI_WORKER`。任务状态变更、事务提交、租约和会话逻辑未搬迁；浏览器句柄仍由 Web UI `session_manager` 持有和释放。依赖方向现为 orchestration 调用 Web UI 服务，Web UI 不反向依赖 orchestration。最终复核发现拆除 ORM 读取后，活跃会话复用查询仍误用了原局部变量 `run.id`；现已改为入口参数 `task_run_id`，新增有效绑定下查询并复用活跃会话的回归用例。对 Web UI 下 `run.*` 和任务 ORM/import 引用的复查未发现其他残留。

## 验证

迁移前基线见 [features-layout-baseline.md](features-layout-baseline.md)。本轮实测：

- 启动导入和 OpenAPI 生成通过：269 paths、418 method/path。通过 `/private/tmp` 中旧目录布局副本与当前布局的逐字段对照，路径、参数、请求体、响应、状态码及 schema 组件相同。唯一 diff 是动态 Mock 路由七个 method 的 `operationId`；FastAPI 从方法集合随机取值，故比较稳定 fingerprint 时剔除此字段。稳定 schema SHA-256 前后均为 `61efb84ca7b41b413e5988b6fd814c07772a0bfd00d1333d22760e9269bf53e7`。
- ORM 结构 fingerprint 与基线相同：112 张表；Alembic 发现导入也实测得到 112 张唯一表。
- 全 backend pytest 收集：基线 1049 项；新增 13 个绑定测试后收集 1062 项。未删除、跳过或修改原测试。
- 修复后 `tests/test_core_consolidation.py` 与 `tests/test_task_web_session_binding.py`：16 passed，1 条 Starlette deprecation warning。
- 修复后重新执行完整 `pytest -q`：578 passed、2 failed、482 errors。482 个 setup errors 和 `test_07_schema_gate.py` 两个失败均因 PostgreSQL 不可达；psycopg 错误为连接 `127.0.0.1:5432` 失败（`Operation not permitted`）。环境未提供 `TEST_POSTGRES_PASSWORD`，临时 placeholder 仅解除测试收集保护，没有数据库可供测试。完整数据库回归因此未完成，以上结果不代表通过。
- `alembic upgrade head --sql` 已尝试，模型环境成功加载并运行到历史 revision `0002`，随后该迁移对 offline `MockConnection` 调用 `inspect()` 而失败（`NoInspectionAvailable`）。按要求没有修改历史迁移脚本。

## 未完成项

- 在可连接的隔离 PostgreSQL 测试库上重跑完整后端回归，确认 API/权限/任务租约/浏览器生命周期数据库路径。
- 重新验证完整 Alembic upgrade 的数据库执行。当前离线生成受历史 revision 0002 的 introspection 限制，且本机 PostgreSQL 不可达。
