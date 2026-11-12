# models/shared 归并 core 交付记录

日期：2026-10-28。工作目录：`/Users/a1/Desktop/ai-test-project`。

## 交付状态

核心代码迁移与调用方收口已完成。交付当时旧导入入口保留并指向同一实现；2026-10-28 后续清理已删除这些纯转发文件并将调用方迁到规范路径，见本文“后续兼容文件清理”。隔离 PostgreSQL 回归已执行；核心回归和所选数据库行为测试通过。全量后端套件未通过，且既有数据库升级与迁移前完整契约快照仍未验证，因此不声明 C0–C5 全部验收通过。

开始时工作区已有大量未提交改动，涉及 Agent、业务 Feature、测试、Alembic 装配和文档。实施前核对并保留这些内容；在调用方文件中仅调整公共模块导入路径及相关说明。历史 `backend/alembic/versions/` 下的迁移文件未修改，未新增迁移。验证使用隔离测试库执行迁移和写入，没有对 `testplatform_dev` 执行迁移或写入。

## 阶段结果

| 阶段 | 已完成工作 | 状态与限制 |
|---|---|---|
| C0：盘点与基线 | 核对工作区状态、旧导入、历史迁移、测试 fixture、`seed_admin.py` 的环境变量顺序；迁移前应用可生成 251 条 OpenAPI path | 部分完成。迁移前未保存完整 OpenAPI JSON，不能做逐项历史 schema 比较。原始 OpenAPI 哈希不适合作为比较值：现有 Mock 通配路由有重复 operationId，重复生成会改变该 operationId。 |
| C1：配置与数据库 | 配置、Base、engine、SessionLocal、get_db 归入 core；Base 单独定义，不加载配置或 session | 代码完成。测试确认新旧 Base、engine、SessionLocal、get_db、settings 同一对象；导入 `app.core` 和 `app.core.models` 不创建 engine。 |
| C2：核心模型 | 四组核心实体归入 `core/models`；只注册九张平台基线表；旧 `app.models` 子模块和历史名称继续兼容；更新当前 Alembic 装配 | 代码完成。四组实体定义与原工作区版本逐文件比较，仅 Base 导入位置变化；历史迁移未改。 |
| C3：公共能力分类 | 安全、HTTP、通知写库能力归入相应 core 子包；原 Agent 与业务脱敏入口继续转发 | 代码完成。旧新模块别名和主要对象身份由定向测试覆盖；认证、权限、通知等所选行为由隔离 PostgreSQL 回归覆盖。 |
| C4：调用方收口 | 当前应用、Agent、Feature、能力包、脚本、Alembic env 与受影响测试改用 core 路径 | 代码完成。静态 AST 检查确认兼容目录之外没有 `app.shared` / `app.models` 活跃导入。历史 `0001` 继续使用旧入口。 |
| C5：验收与交付 | 增加导入、对象唯一性、基线注册兼容测试；完成静态、应用装配和隔离 PostgreSQL 检查 | 部分完成。所选隔离 PostgreSQL 用例通过；全量后端套件有失败/错误，既有库升级与数据保留验证未执行。失败与未完成项见下文。 |

## 规范实现路径

| 目标路径 | 内容 |
|---|---|
| `backend/app/core/__init__.py` | 轻量包入口，不自动加载数据库、模型或业务包 |
| `backend/app/core/config.py` | Settings、settings 与现有运行时密钥读取 |
| `backend/app/core/database/{__init__.py,base.py,session.py}` | 唯一 Base/metadata；唯一应用 engine、SessionLocal、get_db |
| `backend/app/core/models/{__init__.py,identity.py,project.py,configuration.py,notification.py}` | 九张平台核心基线表的唯一 ORM 定义 |
| `backend/app/core/security/{__init__.py,auth.py,roles.py,passwords.py,crypto.py,sensitive.py,sanitizer.py}` | 认证、角色、密码、加密与脱敏 |
| `backend/app/core/http/{__init__.py,dependencies.py,errors.py,pagination.py,rate_limit.py,request_context.py}` | 依赖组合、错误信封、分页、限流与请求上下文 |
| `backend/app/core/notifications/{__init__.py,notify.py}` | 保持吞异常和不阻断主事务的通知写库 |

数据库模型源文件迁移后只更改了 Base 的导入；没有调整列、表名、约束、索引或 ORM 关系。`core.models` 自身只注册九张平台基线表。`backend/alembic/env.py` 改为引用 core Base 和核心注册入口，并保留已有 Agent、MCP、Skill、Tool 与 Task 模型发现导入。

## 调用方与文档路径

- 当前调用方路径：`backend/app/main.py`、`backend/app/agents/`、`backend/app/features/`、`backend/app/{mcp,skills,tools}/`、`backend/scripts/seed_admin.py`、`backend/tests/` 与 `backend/alembic/env.py`。只修改原先引用旧公共模块的导入；`seed_admin.py` 仍先写入 `DATABASE_URL`，再导入会创建 engine 的 session 模块。
- 兼容入口实现：`backend/app/models/`、`backend/app/shared/`、`backend/app/features/agent/providers/sanitizer.py`、`backend/app/features/business/executors/sensitive.py`。
- 新增验证：`backend/tests/test_core_consolidation.py`。
- 文档同步：`docs/coding-conventions.md`、`docs/README.md`、`docs/agent-cluster-refactor/08-directory-refactor.md`、`09-optimization-requirements.md`、`10-core-consolidation-plan.md`、`11-core-consolidation-agent-prompt.md` 与本交付记录。

## 兼容入口

以下表格记录 C 阶段交付当时保留的兼容入口，不代表当前仍存在。后续已按用户要求删除纯转发文件，当前入口清单见“后续兼容文件清理”。

| 旧入口 | 规范实现 |
|---|---|
| `app.models.identity/project/configuration/notification` | `app.core.models` 对应模块 |
| `app.models` 中的核心类与 Base | `app.core.models`、`app.core.database.base`；Agent、Skill、MCP、Tool、ProjectEnvironment 等历史名称继续懒加载到所属包 |
| `app.shared.config` | `app.core.config` |
| `app.shared.database` | `app.core.database.session`；`Base` 从唯一 `core.database.base` 导出 |
| `app.shared.auth/roles/passwords/crypto/sensitive/sanitizer` | `app.core.security` 对应模块 |
| `app.shared.dependencies/errors/pagination/rate_limit/request_context` | `app.core.http` 对应模块 |
| `app.shared.notify` | `app.core.notifications.notify` |
| Agent `providers.sanitizer`、业务 `executors.sensitive` | `app.core.security.sanitizer`、`app.core.security.sensitive` |

交付当时的旧兼容文件通过 `sys.modules` 指向规范模块，因此旧路径导入与规范路径共享模块状态和 monkeypatch 目标。随后 `backend/alembic/versions/0001_initial_schema.py` 与所有活跃调用方已迁到规范导入路径，历史迁移保持未修改。

## 后续兼容文件清理（2026-10-29）

用户要求删除仅做旧路径转发的文件。清理后当前代码不再提供下表中的旧模块入口；这不改变规范实现，也不移除有真实职责的路由或服务。

| 已删除的纯转发入口 | 当前规范入口 |
|---|---|
| `backend/app/models/`、`backend/app/shared/` | `backend/app/core/` 中对应模块；模型从所属 Feature/能力包导入 |
| `backend/app/features/agent/` 下的旧路径文件 | `backend/app/agents/`、`backend/app/tools/`、`backend/app/core/` 下对应模块；Agent 工作流真实实现保留在 `app.agents.workflows.legacy` |
| `backend/app/features/agent_governance/` 的 `catalog.py`、`models/`、`schemas.py`、`services/` 转发文件 | `app.agents`、`app.skills`、`app.mcp`、`app.tools`；实际 `router.py` 保留 |
| `backend/app/features/business/executors/sensitive.py`、`backend/app/features/tasks/runtime/subagents.py` | `app.core.security.sensitive`、`app.agents.runtime.subagents` |
| 五个 Feature `services/_access.py` 转发文件 | 各自的 `services/access_service.py`；带真实实现的 ZAP `services/_access.py` 保留 |
| 前端 Agent、MockManagement、Reports、Tasks、TestManagement 目录纯 re-export `index` 文件 | `frontend/src/App.tsx` 直接懒加载对应页面组件 |

后端测试和运行代码中已无 `app.features.agent.*`、`app.shared.*`、`app.models.*` 旧导入；后续也移除了 `app.agents.schemas` 的通配转发，并将 Agent 节点及受影响测试改为从工具契约模块直接导入。`TaskService`/`TaskWorker` 的方法委托入口和包内公开聚合导出属于现有接口，不是独立兼容文件，按原行为保留。

## 实际验证

| 命令或检查 | 结果 |
|---|---|
| `TEST_POSTGRES_PASSWORD=not-used .venv/bin/python -m pytest tests/test_core_consolidation.py -q` | 4 passed，1 条既有 Starlette/AnyIO 弃用告警。此测试不请求 `db` / `client` fixture、不连接数据库；占位值只满足 conftest 的导入前置条件。 |
| `TEST_POSTGRES_USER=root TEST_POSTGRES_HOST=127.0.0.1 TEST_POSTGRES_PORT=5432 TEST_POSTGRES_PASSWORD=<用户提供值> .venv/bin/python -m pytest tests/test_01_schema_and_seed.py tests/test_02_auth_flow.py tests/test_03_token_revocation.py tests/test_05_isolation.py tests/test_06_persistence.py -q` | `38 passed, 13 warnings, 42.81s`。测试 fixture 在隔离库中从 base 运行 Alembic 至 head；包含 seed、认证/令牌撤销、项目隔离与持久化。未指定 `TEST_DATABASE_NAME`，不会使用 `testplatform_dev`。 |
| `TEST_POSTGRES_USER=root TEST_POSTGRES_HOST=127.0.0.1 TEST_POSTGRES_PORT=5432 TEST_POSTGRES_PASSWORD=<用户提供值> .venv/bin/python -m pytest -q` | `947 passed, 69 failed, 13 errors, 92 warnings, 310.85s`；未通过全量验收。13 个错误包括 6 个 Agent node 源文件被 pytest 当测试收集、缺少 `ctx` fixture，以及 `tests/test_27_langfuse_tracing.py` 的 7 个 setup 错误（模块没有 `_build_client`）。失败主要集中在 `test_29_zap_scan.py` 及 ZAP/Agent Web 流程测试，相关请求返回 404 或无法取得目标 ID；这些 API/功能行为不属于本次 core 模块迁移范围。全量运行中的 core 基线表断言因其他测试提前注册 Feature 模型而失败，随后将该断言改为子进程隔离。 |
| `TEST_POSTGRES_PASSWORD=not-used .venv/bin/python -m pytest -q -k core_consolidation` | `4 passed, 1025 deselected, 67 warnings, 3.02s`。完整测试收集后只运行 core 归并测试，确认 metadata 注册范围断言与测试模块导入顺序隔离。 |
| `.venv/bin/python -m compileall -q app alembic/env.py scripts tests` | 通过。 |
| 导入对象唯一性测试 | Base、metadata、engine、SessionLocal、settings、get_db、四组核心模型及旧模块别名一致；SessionLocal 三个 flag 与既有值一致。 |
| 核心注册测试 | `app.core.models` 与 `app.models` 只注册九张基线表；不因模型包导入创建 session engine 或加载 Feature/Agent。 |
| 当前 OpenAPI 生成 | 成功，251 paths、390 operations；迁移前记录为 251 paths。现有 `/api/v1/mock/{project_id}/{service_key}/{path}` 通配路由有多方法重复 operationId，重复生成的 operationId 会变化，故 raw schema 哈希不稳定；path 数量相同不替代完整接口行为回归。 |
| `.venv/bin/alembic heads` | `0029 (head)`。 |
| `DATABASE_URL='postgresql+psycopg://user:placeholder@127.0.0.1/test_core' .venv/bin/alembic upgrade head --sql > /dev/null` | 失败于历史 `0002_add_bug_table.py` 对离线 `MockConnection` 调用 `inspect()`（`NoInspectionAvailable`）。离线执行已进入 `0001` 并完成其基线步骤，但这不是数据库升级验证。 |
| 活跃旧导入 AST 检查 | 兼容目录之外剩余 `app.shared` / `app.models` 导入数为 0。 |
| 核心模型源定义对比 | 四个迁移前受版本控制的核心模型文件与新文件对比，仅 Base 导入路径不同。 |
| `git diff --name-only -- backend/alembic/versions` | 无输出；历史迁移未修改。 |
| 隔离库与目标库检查 | 测试后只读查询确认 `testplatform_dev` 仍存在，且 `testplatform_gate`、`testplatform_gate_create`、`testplatform_seedtarget` 不存在。目录中另有 7 个 `testplatform_test-p<PID>` 名称的数据库；因没有运行前目录快照，无法归属到本次或既有测试会话，未删除或修改。 |
| `git diff --check` | 报告四处文件末尾空行：`features/business/services/__init__.py`、`features/mock_management/services/__init__.py`、`features/security_testing/services/__init__.py`、`features/test_management/services/__init__.py`。这些文件在本次开始前已是未提交改动；本次没有为此清理其内容。 |

## 未完成事项

1. 全量后端 suite 仍有 `69 failed, 13 errors`；需先区分并处理 pytest 错误收集、Langfuse 测试基线和 ZAP/Agent Web API 测试失败，再复跑完整套件。不能把当前全量回归标记为通过。
2. 尚未对已有隔离库做升级与数据保留验证；本轮空库从 base 到 head 及 seed/认证/隔离/持久化用例已通过。没有对 `testplatform_dev` 执行迁移或写入。
3. 迁移前没有保存 OpenAPI JSON，且当前已有通配路由的重复 operationId 使生成哈希不稳定；因此不能据此宣称完整接口契约逐项相同。当前代码未修改路由、schema 或权限逻辑。
4. 离线迁移在 0002 的 `inspect(MockConnection)` 处受历史迁移实现限制；实际空库迁移已由 pytest fixture 完成，但离线 SQL 生成仍不通过。
5. PostgreSQL 目录中发现 7 个带进程后缀的 `testplatform_test-p<PID>` 数据库。由于执行前没有数据库目录快照，不能安全确认其所有者或来源；本轮未清理这些库，以免删除既有数据。

## 回退说明

本次无 schema 变化、无新 revision，回退不执行数据库 downgrade。代码回退需在恢复兼容文件前同步恢复调用方导入；不得并存两套核心实现。保留既有迁移文件及用户原有改动。
