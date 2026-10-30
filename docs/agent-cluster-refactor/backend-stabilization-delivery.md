# 后端稳定化交付记录（F0–F4）

日期：2026-10-29。实施依据：[16 后端稳定化与拆分计划](16-backend-stabilization-and-split-plan.md) 和 [17 后端稳定化 Agent 提示词](17-backend-stabilization-agent-prompt.md)。

本轮完成 F0–F4。保留现有 HTTP 路径、权限判定、事务边界、人工审批、任务控制行为与数据库结构；没有新增迁移，也没有恢复已删除的兼容目录。D1–D4 只列为后续待办。

## 修复内容

### F1：ZAP 装配、治理引用和审批

- 在 `backend/app/main.py` 注册 ZAP 管理路由，并按 `ZAP_ENABLED` 管理 `ScanWorker` 生命周期。应用启动中途失败和正常关闭时都会释放已启动 Worker；ZAP 关闭时不启动扫描 Worker。
- 治理路由中涉及 Agent 引用的 Skill 更新、恢复、用量查询、删除及 MCP 删除改走 Agent 协调服务，由协调层保护正在引用的资源。治理回归覆盖引用中的删除/恢复冲突、用量查询，以及解除引用后允许删除。
- 在 Agent 图中接入安全扫描规划、人工复核和任务创建节点。LLM 意图只能生成只读计划；只有人工提交的确认 action 才能创建扫描任务。启用主动扫描仍要求确认说明来自 action payload，不能由模型消息伪造。原权限和任务状态转换保持不变。

### F2：共享 HTTP 执行边界

- `backend/app/execution/http/executor.py` 对显式 JSON `null` 发送字面量 `null`，并在未指定时使用 JSON content type；调用方提供的 header 仍优先。
- UTF-8 先组合分块字节后解码，避免多字节字符恰好跨 64 KiB 边界时被替换字符破坏；非法 UTF-8 仍按原有替换策略处理。
- 超时覆盖整个请求、响应头和响应体读取周期，不只限制 connect/read 单阶段。超时会取消流读取并关闭响应和 client；同步 API 在已有 asyncio event loop 中也可调用。
- 截断长度、重定向策略、环境代理策略、返回结构及调用方接口未变。

### F3：测试入口与浏览器登录超时

- 测试按规范模块导入 Agent intent；`ProductionLLMProvider` monkeypatch 改到实际构造它的模块，避免 patch 无效。
- 新增根目录及 `backend/pytest.ini`，分别将默认收集范围固定为 `backend/tests` 和 `tests`。默认 pytest 不再把 `app/agents/workflows/legacy/nodes/test_*.py` 中三个生产函数当作测试执行。
- 浏览器登录超时根因已定位：Playwright 使用随机 Vite 端口，而临时后端仍只允许默认 5173 CORS origin，登录 API 因 origin 检查返回 403，页面随后一直等待登录完成。测试启动临时后端时改为允许本次随机 origin，并把 Vite API proxy 指向同一临时后端；测试现断言经代理登录返回 200、HttpOnly 登录 cookie 存在且未向页面返回 token。登录后的实际路由是 `/console`，测试不再等待旧的 `/admin/dashboard`。
- 浏览器测试只记录 cookie 是否存在，不写出 cookie/token 值；API 错误、页面异常与非预期控制台错误仍会使测试失败。测试仅对三个完整匹配的 Ant Design `rowKey`、Modal `destroyOnClose` 和 Spin `tip` 弃用提示做分类；其它控制台错误不放行。既有未认证 `GET /api/v1/me` 401 单独按请求路径和未认证 cookie 状态核对。诊断收紧时，focused 测试曾因这三条提示通过 console.error 输出而失败；将这三条改为精确匹配后，浏览器用例 1 passed、11 warnings，登录和控制台流程均完成。

## 分阶段实测

所有 PostgreSQL 测试通过用户提供的测试库凭据连接 `127.0.0.1:5432`。运行时清除 `TEST_DATABASE_NAME`，fixture 只创建并删除 `testplatform_test-p<PID>`；没有使用 `testplatform_dev`。凭据没有写入本报告或验证资产。

| 阶段 | 实际结果 |
|---|---|
| F0 修复前默认收集 | 1035 collected：963 passed、69 failed、3 errors、0 skipped、79 warnings。3 个 error 是生产函数误收集。 |
| F0 修复前 `tests/` | 1032 collected：963 passed、69 failed、0 errors、0 skipped、46 warnings。69 个失败 nodeid 已逐项保存。 |
| F1 目标回归 | ZAP、审批与治理目标组在浏览器配置修正前为 171 passed、1 failed；唯一失败为上述浏览器登录 403/超时。修复测试 origin/proxy 后，浏览器场景单项 1 passed、11 warnings。 |
| F2 HTTP 执行器 | `test_business_capability_extraction.py`：15 passed，覆盖 null、JSON 序列化、UTF-8 跨块、非法 UTF-8、截断、总超时、流关闭和已有 event loop 调用。 |
| F3 收集与导入 | 从仓库根目录和 `backend/` 默认 `--collect-only -q` 均为 1042 tests collected；`compileall` 对 app、tests、scripts 和 Alembic env 检查退出码 0。 |
| F4 后端全量回归 | `1042 passed, 47 warnings in 295.23s`，退出码 0；0 failed、0 errors、0 skipped。JUnit：`/private/tmp/backend-stabilization-postfix-final.xml`（临时文件）。 |

最终 47 条 warning 按 pytest 汇总为：24 `DeprecationWarning`、11 `UserWarning`、10 `PytestCollectionWarning`、1 `InsecureKeyLengthWarning`、1 `SAWarning`。它们来自 anyio/Starlette/httpx 弃用、Pydantic 字段名提示、FastAPI 重复 operation id、被导入的 ORM `Test*` 类、一个短测试 JWT key 和一项既有 SQLAlchemy 测试数据提示；都没有被过滤或通过削弱断言处理。F3 修复的是三个生产函数误收集；ORM 类型警告仍存在，但没有作为测试收集。

全量命令（密码由本机环境提供，值不写入命令记录/文档）：

```bash
cd backend
env -u TEST_DATABASE_NAME \
  TEST_POSTGRES_USER=root \
  TEST_POSTGRES_PASSWORD="${TEST_POSTGRES_PASSWORD:?请设置测试库口令}" \
  TEST_POSTGRES_HOST=127.0.0.1 \
  TEST_POSTGRES_PORT=5432 \
  .venv/bin/python -m pytest -q --tb=no -ra --junitxml=/private/tmp/backend-stabilization-postfix-final.xml
```

## 逐项差异与归类

- F0 `tests/` 的 69 个失败 nodeid 在最终运行中全部变为 passed；剩余基线失败 0。
- 新失败 nodeid：0。新增的 10 个测试 nodeid 全部通过；没有从 F0 `tests/` 删除测试。
- 默认收集额外的 3 个 error nodeid 属于 `app/agents/workflows/legacy/nodes/test_{case_generator,planner,point_generator}.py` 的生产函数，被 `testpaths` 收集边界排除；它们不是被标为 skipped 的测试。
- F0 的 69 个失败只能确定为本轮修复前基线；缺少更早的逐 nodeid 报告，无法判定这些失败在历史上何时引入，故历史来源标为未知，不将其伪称为新增或历史遗留。
- 最终 1042 个已收集测试全部执行，无 skipped。未覆盖项见下方：没有对真实外部 OWASP ZAP 引擎发起扫描；验证的是后端 API、Worker 生命周期与人工审批测试。独立 Agent 页面目前也没有展示 ZAP 计划和审批说明输入控件；本轮只完成后端能力与现有控制台浏览器回归，没有扩展该页面。

逐 nodeid 数据：

- [F0 完整逐项基线](backend-stabilization-validation/20261029-pre-fix/cases.json)
- [F0 基线摘要与失败列表](backend-stabilization-validation/20261029-pre-fix/summary.json) · [失败 nodeid](backend-stabilization-validation/20261029-pre-fix/failures.json)
- [F4 完整逐项结果](backend-stabilization-validation/20261029-post-fix/cases.json)
- [F4 摘要](backend-stabilization-validation/20261029-post-fix/summary.json) · [nodeid 前后差异](backend-stabilization-validation/20261029-post-fix/nodeid-diff.json) · [失败 nodeid](backend-stabilization-validation/20261029-post-fix/failures.json)

## D1–D4 后续待办

- **D1 执行契约与准备：** 隔离 Web UI adapter 对 `test_case_executor` 私有 helper 的依赖，再按需拆公开结果契约和数据准备；保留 Fixture、人工确认与执行落库行为。
- **D2 任务运行控制：** 按 T4–T6 方向拆分任务运行、计划、命令及 runtime lease/completion；保持批准版本、幂等、行锁、租约、迟到结果和事务语义。
- **D3 安全域内部：** 梳理 ZAP connector、orchestrator、runner 的协议调用、能力探测、扫描阶段和结果归一化；不另建扫描队列、不把安全业务逻辑泛化进 HTTP 底座。
- **D4 目录服务与 schema：** 按资源拆 API catalog 服务和大 schema；保持当前接口、字段、分页、顺序及公开入口。

D 阶段不属于本次交付；开始前应重新保存稳定基线并单独安排实施和验收。

全仓 `git diff --check` 仍报告 4 个既有文件末尾空行：`backend/app/features/business/services/__init__.py`、`backend/app/features/mock_management/services/__init__.py`、`backend/app/features/security_testing/services/__init__.py`、`backend/app/features/test_management/services/__init__.py`。这些差异在 F0 修复前工作区已存在，本轮没有改动它们。对本轮涉及的已跟踪代码与文档执行的定向 `git diff --check` 退出码为 0。

## 回退方式

F0 时工作区已经有 426 个跟踪路径改动和 51 个未跟踪路径，且包含本轮之前的模块迁移与已删除兼容目录。没有对整个 worktree 建立覆盖式备份，因此**不得**用 `git reset --hard`、批量 `git checkout` 或整目录删除来回退；那会丢失用户已有修改。

若需撤销本轮行为，应以本报告修复项为边界，对 `backend/app/main.py`、`backend/app/agents/`、`backend/app/features/agent_governance/router.py`、`backend/app/execution/http/executor.py` 和相关测试/pytest 配置逐个反向撤销本轮代码块，同时保留同文件原有差异；先通过 `git diff` 核对每个 hunk，再应用反向修改。不要恢复已经删除的兼容目录。没有数据库迁移或持久化数据格式变更，所以无需执行数据库回退。


后续入口（2026-10-29）：[后端综合职责拆分 B0–B9](backend-comprehensive-delivery.md)。本文历史范围、结果与限制保持原事实。
