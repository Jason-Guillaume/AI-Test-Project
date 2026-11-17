# Dagu 自动化执行中心整改报告

审查基准：`3d8e8e995bd5fc65d1f9997919ea74ad8e2013ba`（与 `origin/develop` 一致）。
整改工作基于该提交完成。
真实 Dagu 联调：**未完成**。当前环境没有可访问的 Dagu 服务、API Key 或 Codeup Deploy Key。

## 1. 发现的问题

1. `0087` 的 `downgrade()` 在没有 Dagu/LEGACY 数据时也会抛错，历史迁移测试无法穿过这条修订。
2. Jenkins 已退出执行引擎，但迁移只改 `provider_type`，未结束的 `PENDING`/`RUNNING` 记录仍可能被 Poller 当作活跃任务。
3. Dagu 接入后，云效取消不再等停止接口确认就结束，而是和 Dagu 一样只记 `stop_requested`。远端若随后返回成功，平台状态会被轮询改回去。
4. Dagu `enqueue` 发生在数据库提交之前。提交失败或进程中断时，平台记录和远端任务对不上。
5. 手动执行没有数据库唯一约束，重复点击或重试会再次入队。
6. 回调只校验自动化项目属于该 `callback_key`，没有同时校验接入配置、Provider、业务项目和 `dag_run_id`。
7. DAG 名称只做了格式校验，普通成员可以直接提交未审核的 DAG。
8. 私网 HTTP 只要打开开关就接受任意内网地址；HTTPS 字面量内网地址和解析到内网的域名没有白名单。
9. Runner 的虚拟环境缓存把 Git Commit 算进缓存键，同依赖会在每次提交后重装。
10. 执行页按钮可访问名称是“执行”，会和菜单里的“执行任务”等包含该词的控件冲突；项目作用域依赖 `localStorage.user`，和当前登录用户不一定一致。

已核对、本次没有改 API 路径的部分：仓库里没有部署中的 Dagu 版本和 OpenAPI。现有客户端使用 `GET /dags/{name}/dag-runs`、`GET /dag-runs/{name}/{id}`、日志、stop 和 dequeue。没有真实实例前，不按其他版本文档改路径。

## 2. 根本原因

- `0087` 把“有历史数据时不可逆”写成了“任何时候都不可逆”。Jenkins 凭据表被删除后确实无法恢复密文，但空库只需要恢复表结构。
- 取消逻辑在去掉 Jenkins 时被收成一条异步路径。云效原来的 `stop_run` 返回确认后就会把记录写成 `CANCELLED`，并且不留下 `stop_requested_at`，所以后续轮询看到终态会直接返回。
- 触发流程先 `flush` 再调用 Provider，最后才 `commit`。Dagu 使用 `automation-{execution_id}` 作为稳定运行 ID，这个 ID 必须先落库，超时后才能按它查询而不是再入队。
- 回调解析按 `execution_id` 找到记录后，只比较了 `automation_project_id`。报告解压发生在运行 ID 校验之前的旧顺序里，不匹配的回调仍可能写文件。现已在解压前拒绝。
- DAG 白名单没有放在服务端。前端下拉框不能阻止直接调用 API。
- 缓存键同时包含仓库地址和提交号，依赖清单没有单独决定环境身份。

## 3. 修改的文件

- `backend/alembic/versions/0087_dagu_automation_provider.py`
- `backend/alembic/versions/0088_dagu_dispatch_idempotency.py`（新增）
- `backend/app/core/config.py`
- `backend/app/features/automation_center/models/entities.py`
- `backend/app/features/automation_center/models/__init__.py`
- `backend/app/features/automation_center/providers/dagu_client.py`
- `backend/app/features/automation_center/providers/dagu_provider.py`
- `backend/app/features/automation_center/schemas.py`
- `backend/app/features/automation_center/services/center_service.py`
- `backend/app/features/automation_center/router.py`
- `deploy/dagu/runner.py`
- `frontend/src/pages/console/AutomationCenter/Runs.tsx`
- `frontend/e2e/automation-dagu.spec.ts`
- `backend/tests/test_22_security_strategy.py`
- `backend/tests/test_78_automation_center.py`
- `backend/tests/test_automation_dagu_client.py`
- `backend/tests/test_automation_dagu_migrations.py`
- `backend/tests/test_automation_dagu_provider.py`
- `backend/tests/test_automation_dagu_runner.py`
- `backend/tests/test_automation_dagu_service.py`
- `docs/automation-center-dagu.md`
- 本报告

未纳入本次改动：`.idea/`、`docs/platform-fixes-2026-11-12.md`。

## 4. 修改前后的差异

| 行为 | 修改前 | 修改后 |
|---|---|---|
| `0087` 降级 | 始终抛错 | 无 Dagu/LEGACY 数据时恢复 Jenkins 列、唯一索引和空凭据表；有这类数据时拒绝并回滚 |
| 未完成的 Jenkins 记录 | 只改成 `LEGACY` | 另外写成 `CANCELLED`，原状态保存在 `legacy_provider_identifiers` |
| 云效取消 | 只记停止请求 | 停止接口确认后立即 `CANCELLED`，重复取消保持终态，后续同步不再覆盖 |
| Dagu 取消 | 与云效混用 | 仍记 `stop_requested`，由 Poller 在 `aborted` 或停止后的 404 上确认 |
| Dagu 触发 | 先入队再提交 | 先提交 `automation-{id}` 和 `dispatch_state=PENDING`，再入队；超时、409、429、5xx 先按稳定 ID 查询 |
| 执行幂等 | 无 | `Idempotency-Key` 或请求体 `idempotency_key`，数据库唯一约束；参数不同返回 409 |
| 回调归属 | 主要看自动化项目 | 配置启用、配置 ID、Provider、两个项目 ID、Dagu Run ID 必须一致；不匹配不写报告、附件或通知 |
| DAG | 格式合法即可 | 只允许 `automation-pytest-allure`，创建、修改、触发和 DAG 列表都检查 |
| Dagu 地址 | 开关打开后任意私网 HTTP | HTTP 和内网 HTTPS 都必须出现在 `DAGU_PRIVATE_HOST_ALLOWLIST`；真实连接会检查 DNS |
| Python 缓存 | 含 Git Commit | 按 Python 版本、操作系统、架构和依赖清单计算；过期且未加锁的环境才删除 |

## 5. 数据库迁移

`0087` 仍负责把 Jenkins 接入改成停用的 `LEGACY`，把 Queue/Build 号写入 `run_params.legacy_provider_identifiers`，并删除无法恢复的 Jenkins 凭据表。不能安全恢复的数据是：Jenkins API Token、原接入的启用状态，以及已经从列上卸下的 Dagu API Key。没有这些行时，降级会把列和空表加回来，供 `0085` 的降级继续删除。

`0088` 增加：

- `automation_execution.dispatch_state`，已有行默认 `CONFIRMED`，避免升级后重放历史任务。
- 索引 `ix_automation_execution_dispatch`。
- `automation_execution_idempotency`，唯一键是 `(automation_project_id, idempotency_key)`。过期清理只删除已经进入终态的收据。

## 6. 安全加固

- API Key 和回调密钥继续只存密文，响应只返回是否已配置。
- 日志替换 API Key，以及 `token`/`secret`/`password` 这类赋值。
- 公网 HTTP 拒绝。内网地址必须同时打开 `DAGU_ALLOW_INSECURE_HTTP` 并列入白名单。
- 客户端禁用重定向和环境代理。真实请求解析 DNS，解析到私网、回环或链路本地地址时，主机必须在白名单中。
- HMAC-SHA256、常量时间比较、300 秒时间窗和回调幂等收据保持不变。
- Allure 统计以报告文件为准，回调元数据里的用例数字不能覆盖它。
- 附件大小、ZIP 和路径穿越仍由现有 `safe_extract` 拒绝。
- Runner 只接受 Codeup 与 GitHub 的无凭据地址，SSH 命令只带密钥文件路径。

## 7. Provider 状态

平台状态仍是 `PENDING`、`RUNNING`、`SUCCESS`、`FAILED`、`CANCELLED`、`TIMEOUT`。

Dagu 映射：`queued` → `PENDING`，`running` → `RUNNING`，`succeeded` → `SUCCESS`，`failed` / `partially_succeeded` / `rejected` → `FAILED`。`aborted` 在已有取消或超时原因时保留该原因，否则记失败。

Poller 只同步 `DAGU` 和 `YUNXIAO`。`LEGACY` 不进入同步、取消或手动同步。单条异常回滚后继续下一条。终态且没有未确认停止请求时，普通轮询直接返回。Dagu 投递未确认时先补投，不按运行详情覆盖。执行超过 30 分钟仍未结束会写警告日志。

## 8. Runner

依赖缓存不再包含 Git Commit。相同 `requirements.txt`、Python、系统和架构复用同一虚拟环境；依赖内容变化后使用新键。创建仍使用锁和临时目录原子替换。14 天未使用且拿不到独占锁的环境会被清理，正在使用的环境跳过。

另外限制了最小剩余磁盘和并发槽位，默认至少保留 1 GiB、最多 2 个并发任务。日志仍限制为最近 2 MB。每次运行使用独立工作目录。

## 9. 前端

- 执行按钮在请求未结束时不能再次提交，并为每次提交生成幂等键。
- `LEGACY` 项目不能选择后执行，取消和同步保持不可用。
- 执行按钮的可访问名称是“执行自动化测试”，取消按钮是“取消执行”，避免和“执行任务”菜单匹配。
- 日志加载失败时可以重试。
- E2E 用 `/me` 的用户 ID 写入项目作用域，再等待项目下拉框出现。

## 10. 新增或加强的测试

- 空库可以从 `0088` 降到 `0086` 并恢复 Jenkins 结构；插入 `LEGACY` 后降级被拒绝且数据还在。
- 未完成的 Jenkins 行归档为 `CANCELLED`，云效行不变。
- 云效取消后立即为 `CANCELLED`，重复取消和再次同步不改变该状态。
- Dagu 入队 500 且远端不存在时不假装成功；远端已存在时按稳定 ID 恢复。
- 非白名单 DAG 返回 400。相同幂等键只入队一次，不同分支返回 409。
- 伪造的 Dagu Run ID 不改状态、不产生报告；正确回调可重复提交并标记为重复。
- 私网 HTTP 必须同时具备开关和主机白名单。
- 依赖缓存不因提交号变化，依赖内容变化后不复用。
- 安全策略降级改到独立空库，避免共享库里的回收站记录阻断 `0081`。

## 11. 测试执行结果

| 检查 | 结果 |
|---|---|
| 自动化与云效定向测试 | 27 通过 |
| `test_22` 独立降级、Web/ZAP 迁移降级和 head 断言 | 8 通过；隔离调整后 `test_22` 降级再跑 1 通过 |
| 前端 `npm test` | 41 通过 |
| 前端 typecheck、ESLint、Vite build | 通过 |
| Dagu Playwright 用例 | 通过（安装 Chromium 后） |
| 后端全量 pytest | 1224 通过，43 失败，6 错误 |

全量失败没有落在本次新增的 Dagu 用例上。主要是两类：

- Web UI / Agent 用例需要本机 Playwright Chromium。全量运行时浏览器尚未安装，错误是 `Executable doesn't exist`。安装发生在这次全量之后，没有把这 30 多个浏览器用例整套重跑。
- `test_02`、`test_05`、`test_06`、`test_74`、`test_api_catalog` 的失败与自动化中心无关，表现为注册计数、平台管理员权限或用户删除后的关联计数。`test_22` 在全量里的失败点是 `0081` 的模型配置回收站保护，发生在 `0087` 已成功降级之后；该用例现已改到干净库。

## 12. GitHub Actions

仓库日志接口返回 `403 Must have admin rights`，拿不到失败用例正文。能看到的作业结论：

| 提交 | 前端 | 后端 | E2E |
|---|---|---|---|
| `370db54`（Dagu 之前） | 成功 | 失败 | 失败 |
| `3d8e8e9`（本次审查基准） | 成功 | 失败 | 失败 |

因此不能把基准提交上的后端和 E2E 失败全部算成 Dagu 引入的回归。前端在两个提交上都是成功的。本次改动还没有推送，没有新的 Actions 运行。

## 13. 尚未解决的问题

- 全量后端里与浏览器、用户生命周期和接口目录有关的失败没有在本次逐条修复。它们在 Dagu 之前的 Actions 后端作业中已经表现为失败，本次没有日志能逐项对照。
- `0081` 及更早的回收站迁移在共享库已有删除数据时仍会拒绝降级。这是原有保护，不是 Dagu 数据问题。安全策略这条降级已改到空库。
- Dagu 运行列表路径没有对照真实 OpenAPI 修改。

## 14. 真实部署和联调

未完成。阻塞原因：没有 Dagu Base URL、API Key、回调公网 HTTPS 地址，也没有 Codeup/GitHub Deploy Key。Mock 测试不能代替这条验收。

因此没有真实的成功、失败、取消和超时执行。

## 15. 上线前需要人工完成的配置

1. 设置 `PUBLIC_APP_BASE_URL` 为平台 HTTPS 地址。
2. 在项目里创建 Dagu 接入，只保存 API Key 的密文。
3. 若 Dagu 在内网：设置 `DAGU_ALLOW_INSECURE_HTTP=true`，并把主机名写入 `DAGU_PRIVATE_HOST_ALLOWLIST`。公网必须使用 HTTPS。
4. 把 `automation-pytest-allure.yaml` 安装到 Dagu，队列名使用 `automation-tests`。
5. 在执行机放置 Deploy Key、`known_hosts`，以及按接入配置 ID 命名的回调密钥文件。私钥不要写入日志或 DAG 参数。
6. 执行 `0088` 迁移。
7. 用真实仓库各跑一次成功、失败、取消和超时，再核对 Allure、Poller 和执行历史。

## 命令

```bash
cd backend
.venv/bin/python -m alembic upgrade head

cd backend
.venv/bin/python -m pytest -q tests/test_automation_dagu_migrations.py tests/test_automation_dagu_client.py tests/test_automation_dagu_provider.py tests/test_automation_dagu_runner.py tests/test_automation_dagu_service.py tests/test_automation_dagu_callback.py tests/test_78_automation_center.py

cd frontend
npm test
npm run typecheck
npm run lint
npm run build

bash scripts/e2e_case_generation.sh e2e/automation-dagu.spec.ts
```

Dagu 部署沿用 `deploy/dagu/README.md`：安装 Runner、DAG、队列配置和清理 timer。真实联调顺序是：配置 API 地址与白名单、测试连接、只绑定 `automation-pytest-allure`、配置 Deploy Key、触发执行、等待回调和 Poller，再打开 Allure。
