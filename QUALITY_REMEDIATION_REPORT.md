# AI-Test-Project 全量工程质量整改报告

**工作分支**：`feature/quality-remediation`（基于 `develop@fe13026` 切出）  
**整改基准提交**：`fe13026`（`feat: integrate defect sharing and Dagu remediation`）  
**执行原则**：先理解现有实现并重新建立真实基线，不删减业务功能、不降低权限或安全断言、不用 Mock 替代真实浏览器/数据库验证；受外部隔离环境限制无法联网验收的项明确标注 `BLOCKED`。

---

## 一、本次整改范围与基线对比

| 验收维度 | 历史审查参考（prompt 描述） | 本机基线实测（`fe13026`） | 整改后最终验收结果 |
|---|---|---|---|
| 后端主测试集 `backend/tests` | 1237 passed / 42 failed / 6 errors | **1272 passed / 7 failed / 6 errors** | **1312 passed / 0 failed / 0 errors**（615.26s） |
| 后端嵌套模块测试（4 模块） | — | 已通过基线校验 | **120 passed / 0 failed / 0 errors**（10.68s） |
| 真实外部集成测试 `backend/integration_tests` | 缺少真实联调测试 | 无独立集成套件 | **2 skipped（`BLOCKED`：未配置隔离 Dagu / 飞书测试群）** |
| 前端 Node 单元测试 `npm test` | 40 passed / 1 failed（71 vs 70） | **40 passed / 1 failed** | **51 passed / 0 failed**（2.51s） |
| 前端 TypeScript / ESLint / Vite Build | Build 未完成有效验收 | 需对齐验收 | **`tsc -b --noEmit` / `eslint --max-warnings=0` / `vite build` 全部通过（6.42s）** |
| Playwright E2E（独立库与服务） | 30 passed / 5 failed | **31 passed / 4 failed** | **35 passed / 0 failed（7.4m）**，覆盖 62 路由 × 6 视口 |
| Alembic 迁移检查 | 单 head 校验 | 需审计 `0087~0089` | **`0089 (head)` 单 head；迁移升级/审计全通过** |
| GitHub Actions CI 门禁 | 流水线覆盖不足 | 缺 Redis / Chromium / 安全审计门禁 | **升级为 6 阶段完整门禁**（[quality.yml](.github/workflows/quality.yml)） |

---

## 二、问题清单与整改明细（按 P0 → P1 → P2 分类）

> 说明：每一项均严格区分「代码/逻辑问题」与「运行环境/配置问题」，无删减断言或跳过测试。

### P0-1：前端路由完整性断言不一致与公开/受保护路由、Nginx SPA 回退校验
- **所属模块**：前端路由与 Nginx 入口
- **文件位置**：[frontendRoutes.test.mjs](frontend/tests/frontendRoutes.test.mjs)、[App.tsx](frontend/src/app/App.tsx)、[nginx.conf](frontend/nginx.conf)
- **复现步骤**：在 `frontend/` 执行 `npm test`，路由契约测试抛出 `ERR_ASSERTION: 71 !== 70`。
- **根本原因**：新增公开缺陷分享路由 `/public/defect-shares/:shareId` 后，`frontendRoutes.test.mjs` 仍使用过时的静态数量 `70` 与笼统数量断言，未结构化校验「既有路由不缺失 + 新增路由显式声明 + 守卫边界（`/public/defect-shares/:shareId` 不受 `RequireAuth` 拦截）+ Nginx SPA fallback」。
- **是否本次新增回归**：是（`fe13026` 合入缺陷分享路由后测试未同步更新）。
- **修复方案**：重构 `frontendRoutes.test.mjs` 为基于 AST 解析与集合显式对比测试：校验路由树无重复无缺失 `element`、70 条既有路由全保留、新增路由显式登记、`/public/*` 顶层无平台登录守卫、`/admin/*` 走 `RequireAdmin`、`/console/*` 走 `RequireAuth`，并静态校验 `frontend/nginx.conf` 对非 `/api/` 路由执行 `try_files $uri $uri/ /index.html`。
- **对应测试与结果**：`npm test` 中路由专项全部通过（含在 `51 passed, 0 failed` 内）。

### P0-2：Playwright 浏览器容器环境、并发启动与超时槽位释放
- **所属模块**：Playwright 浏览器执行器与 Web Agent 会话管理
- **文件位置**：[playwright_executor.py](backend/app/execution/browser/playwright_executor.py)、[session_manager.py](backend/app/execution/browser/session_manager.py)、[backend/Dockerfile](backend/Dockerfile)、[.github/workflows/quality.yml](.github/workflows/quality.yml)
- **复现步骤**：Linux/Docker/CI 无 Chromium 或缺少系统依赖时直接报 `Executable doesn't exist`；浏览器命令挂死或同一 `session_id` 并发 `open()` 时可能发生槽位泄漏或双开会话。
- **根本原因**：
  1. CI 未按后端 venv 执行 `playwright install --with-deps chromium`，且缺少容器下所需的 `--no-sandbox`、`--disable-setuid-sandbox` 与 `--disable-dev-shm-usage` 区分逻辑；
  2. `BrowserSession._call()`、`close()` 使用无超时 `Event.wait()` 与 `thread.join()`，底层 Playwright 卡死会导致 `_SLOTS` 信号量永久无法释放；
  3. `SessionRegistry.open()` 仅在查表阶段持全局锁，并发打开同一 `session_id` 时可能同时启动多个 Chromium 再关闭旧实例；
  4. 缺失浏览器或系统依赖时返回通用错误，难以区分环境缺失（`WEB_BROWSER_ERROR` + 安装指引）与操作超时（`WEB_TIMEOUT`）。
- **是否本次新增回归**：既有隐患 + CI 环境配置缺失。
- **修复方案**：
  - 在 `playwright_executor.py` 新增 `chromium_launch_args()` 与 `classify_browser_error()`，按运行环境注入 `--disable-dev-shm-usage` 及 Linux/root/容器 `--no-sandbox` 参数，明确区分缺失 Chromium/系统依赖与超时错误码。
  - 在 `session_manager.py` 为 `_call()` 与 `close()` 引入超时控制（`_DEFAULT_COMMAND_TIMEOUT_SECONDS = 45.0`、`_CLOSE_WAIT_SECONDS = 5.0`），确保异常与超时路径必定释放 `_SLOTS`；新增按 `session_id` 的 `_OPEN_LOCKS` 串行保护，防止同 ID 并发双开。
  - 完善 `backend/Dockerfile` 与 `.github/workflows/quality.yml`（安装 Chromium 及依赖、加 `chmod -R a+rX /ms-playwright` 并以真实 Chromium 启动自检作为 CI 前置校验）。
- **对应测试与结果**：`tests/test_browser_lifecycle.py`（5 项）以及 `tests/test_30_web_ui.py` ~ `tests/test_35_tasks.py` 全部在全量 `pytest` 中真实浏览器通过（`1312 passed, 0 failed`）。

### P0-3：用户注册个人组织初始化、权限隔离与 API Catalog 删除边界
- **所属模块**：身份认证、组织治理、项目权限与接口目录
- **文件位置**：[user_service.py](backend/app/platform/users/services/user_service.py)、[management_service.py](backend/app/platform/organizations/services/management_service.py)、[organization_service.py](backend/app/platform/organizations/services/organization_service.py)、[project_service.py](backend/app/platform/projects/services/project_service.py)、[roles.py](backend/app/core/security/roles.py)、[module_service.py](backend/app/features/api_catalog/services/module_service.py)、[test_platform_admin_management.py](backend/app/platform/organizations/tests/test_platform_admin_management.py)
- **复现步骤**：运行 `fe13026` 后端基线：`test_02_auth_flow.py`（1 failed）、`test_05_isolation.py`（6 errors）、`test_06_persistence.py`（4 failed）、`test_74_user_lifecycle.py`（1 failed）、`test_api_catalog.py`（1 failed）。
- **根本原因**：
  1. `UserAdminService.register()` 与 `create_by_admin()` 移除了同事务调用 `ensure_personal_organization(db, user)`，导致注册/建号后无个人组织且 `organization.owner_id` 缺失，进而级联破坏用户持久化、删除保留、`purge` 依赖保护与 `test_05_isolation.py` setup；
  2. `management_service.py` 中 `create_organization()` 及 `update_organization()`、`put_member()`、`delete_member()`、`transfer_ownership()` 等错误地校验 `_require_platform_admin(user)`，导致组织 Owner/Admin 返回 `ERR_FORBIDDEN`；
  3. `roles.py` 权限查询存在软删除记录过滤不完整（`Organization.deleted_at`、`OrganizationMember.deleted_at`、`ProjectMember.deleted_at`），以及用户离开组织后未剥夺旧组织内曾留存的 `ProjectMember` 可见性问题；
  4. `module_service.delete_module()` 绕过了 `app.lifecycle.service.delete_resource("api_module", ...)` 的非空模块 `409 Conflict` 保护，直接走批量删返回 `204`。
- **是否本次新增回归**：主要为上一轮重构引发的逻辑退化（与 `fe13026` 前后合并冲突相关）。
- **修复方案**：
  - 恢复 `UserAdminService.register()` 与 `create_by_admin()` 同事务调用 `ensure_personal_organization(db, user)`，任一步异常回滚整笔事务。
  - `management_service.create_organization()` 允许合法登录用户创建组织；单组织更新、候选成员查询、成员授予/移除、所有权转移改为使用基于 `organization_id` 的 `require_organization_admin(db, organization_id, user)`（组织删除/移入回收站仍严格限定平台管理员）；`project_service.py` 复用 `require_organization_admin` 对齐项目创建/转移的组织边界。
  - 加固 `roles.py` 中 `organization_role()`、`project_role_for()`、`accessible_organization_ids()`、`accessible_project_ids()`：过滤所有软删除成员及组织行，`accessible_project_ids()` 使用子查询避免 Join 重复行且确保退出组织立即失去该项目可见性。
  - 恢复 `module_service.delete_module()` 走 `delete_resource(db, "api_module", ...)` 保持单删非空返回 409 语义，与批量删树 `delete_modules` 分离。
- **对应测试与结果**：`test_02_auth_flow.py`、`test_05_isolation.py`、`test_06_persistence.py`、`test_74_user_lifecycle.py`、`test_api_catalog.py`、`test_platform_admin_management.py` 及新增 [test_79_auth_isolation_lifecycle.py](backend/tests/test_79_auth_isolation_lifecycle.py) 全部通过。

### P1-4：缺陷公开分享全链路安全与体验加固（4.1 ~ 4.6）
- **所属模块**：缺陷公开分享（前端页面、推送弹窗、历史记录、后端公开路由、限流与归档）
- **文件位置**：
  - 前端：[shareToken.ts](frontend/src/features/defects/api/shareToken.ts)、[DefectShare/index.tsx](frontend/src/pages/public/DefectShare/index.tsx)、[publicShare.ts](frontend/src/features/defects/api/publicShare.ts)、[DefectShareHistory.tsx](frontend/src/features/defects/components/DefectShareHistory.tsx)、[DefectShareModal.tsx](frontend/src/features/defects/components/DefectShareModal.tsx)、[contracts.ts](frontend/src/features/defects/contracts.ts)
  - 后端：[public_rate_limit.py](backend/app/features/defects/services/public_rate_limit.py)、[public_router.py](backend/app/features/defects/public_router.py)、[share_service.py](backend/app/features/defects/services/share_service.py)、[share_archive_worker.py](backend/app/features/defects/services/share_archive_worker.py)、[schemas_share.py](backend/app/features/defects/schemas_share.py)、[main.py](backend/app/main.py)、[config.py](backend/app/core/config.py)、[card_builder.py](backend/app/orchestration/report_delivery/card_builder.py)
- **核心问题与修复方案**：
  1. **Token 生命周期（4.1）**：提取模块内纯内存管理器 `shareToken.ts`（首帧捕获并立即执行 `history.replaceState` 剥离 URL Fragment；通过组件未挂载延迟/幂等守卫兼容 React 18 `StrictMode` 重挂载不丢凭证；严禁写入 `localStorage`/`sessionStorage`/`cookie`/query/控制台；全页刷新后无内存 Token 时提示通过原分享链接重新进入）。
  2. **分布式限流与反代 IP 提取（4.2）**：`public_rate_limit.py` 引入基于 `redis>=5,<6` Lua 脚本的原子滑动窗口限流（独立维度覆盖 IP、`(ip, share_id)`、`share_id`、以及失败凭证独立桶，区分 `view`/`resolve`/`failure` 操作策略，键摘要使用 HMAC/SHA256 脱敏并设置过期 TTL）。IP 提取基于 `TRUSTED_PROXY_CIDRS` 从右向左仅剥离可信反代（兼容 IPv4/IPv6），防止客户端伪造 `X-Forwarded-For` 绕过；提供 `PUBLIC_SHARE_RATE_LIMIT_FAIL_CLOSED` 控制 Redis 不可用时降级有界内存滑窗或直接拒绝 503。`compose.yaml` 新增 `redis:7-alpine` 服务。
  3. **重新推送体验（4.3）**：`DefectShareHistory.tsx` 重推后展示只读可选中 `<Input>` 新链接、复制按钮（Clipboard API 失败时优雅降级提示手动选择复制而不抛异常）、明确提示旧链接已失效、展示飞书推送结果状态并使用并发守卫禁用连点。
  4. **自动归档与已删缺陷失效（4.4）**：`share_service.py` 抽离幂等 `archive_expired_shares()`，新增后台周期 Worker `share_archive_worker.py` 并在 `main.py` lifespan 注册；校验并阻止已删除缺陷（`Bug.deleted_at`）或已撤销/已归档链接继续访问；修正 `record_view` 原子 SQL 更新消除并发计数覆盖竞态；归档失败记录错误并支持下次调度重试。
  5. **生产 URL 配置校验（4.5）**：新增 `validate_public_share_base_url()` 校验 `PUBLIC_APP_BASE_URL`（生产 `APP_ENV=production` 强制非空完整 `https://` 域名，拒绝内网开发地址与相对路径），并在 `SharePreviewResponse` 返回 `public_url_valid`/`public_url_error`，前后端均清晰提示错误而不伪装成功；`scripts/e2e_case_generation.sh` 注入隔离测试 `PUBLIC_APP_BASE_URL`。
  6. **飞书卡片与输入安全（4.6 & P2）**：`card_builder.py` 新增 `_safe_md_text()` 转义危险标记并限制字段长度，防止长文本或特殊字符破坏卡片结构或泄露内部信息；补充 `test_89b_defect_share_security.py`（含真实 `redis:7-alpine` 容器联测多实例限流、IPv4/IPv6 伪造防护、重放/并发/跨项目/过期/失效/降级）与 `test_89c_feishu_card_reliability.py`。
- **对应测试与结果**：前端 [defectShareToken.test.mjs](frontend/tests/defectShareToken.test.mjs) 全过，后端 `test_89_defect_public_share.py`、`test_89b_defect_share_security.py`、`test_89c_feishu_card_reliability.py` 全过；真实飞书外部群 Webhook `integration_tests/test_feishu_integration.py` 标记为 `BLOCKED`。

### P1-5：Dagu 自动化执行中心兼容性、SSRF/DNS Rebinding 与生命周期加固
- **所属模块**：自动化执行中心 & Dagu Runner
- **文件位置**：[status.py](backend/app/features/automation_center/providers/status.py)、[dagu_client.py](backend/app/features/automation_center/providers/dagu_client.py)、[dagu_provider.py](backend/app/features/automation_center/providers/dagu_provider.py)、[center_service.py](backend/app/features/automation_center/services/center_service.py)、[deploy/dagu/runner.py](deploy/dagu/runner.py)
- **根本原因与修复方案**：
  1. `status.py` 对齐 Dagu OpenAPI v2.26.0，将 `NOT_STARTED` 与 `WAITING`/`QUEUED` 规范映射为平台 `PENDING`。
  2. `dagu_client.py` 实现自定义 `_PinnedSyncBackend` 强制将已校验 IP 固定绑定到 TCP Socket（彻底封堵 DNS Rebinding）；`list_runs()` 支持 `limit` 与 `nextCursor` 翻页；`list_dags()` 兼容分页读取。
  3. `dagu_provider.py` 扩展 `stop_run()` 覆盖 `waiting`/`not_started` 等待态取消，兼容 `/openapi.json` 返回 403/404 时的能力探活降级。
  4. `center_service.py` 在 `_dispatch_dagu` 增加提交超时过期收敛、保留并行取消意图不被迟到派发覆盖，规范状态转移 `_transition`。
  5. `deploy/dagu/runner.py` 为 `git clone` 增加 `--` 参数分隔符防范分支名参数注入，并在 `finally` 块确保并发锁与运行槽位释放。
- **对应测试与结果**：[test_automation_dagu_remediation.py](backend/tests/test_automation_dagu_remediation.py)（6 项）与 `test_automation_dagu_service.py`、`test_78_automation_center.py` 全过；真实 Dagu 实例 `integration_tests/test_dagu_integration.py` 标记 `BLOCKED`。

### P1-7 & 后端真实控制台回归：Playwright E2E、全路由响应式及控制台交互缺陷
- **所属模块**：前端布局响应式、页面生命周期、Ant Design 表单契约与 E2E 测试
- **主要根因与修复方案**：
  1. **E2E 基线 4 个原失败修复**：
     - `all-routes-responsive.spec.ts`：由无效的 `history.pushState` 切换为真实 `page.goto()` 并扩展验证 6 种分辨率（`1920×1080` 到 `390×844`），放行已纳入 `expectedBusinessErrors` 的 `/api/v1/*` 403/404 浏览器网络资源日志同时严控 JS/React 控制台零报错；
     - `data-lifecycle.spec.ts` & `RecycleBinPage.tsx`：修正选择器与缓存失效刷新超时；
     - `ModelCenterPage.tsx` & `AppProviders.tsx`：修复 `canDiagnoseProject` 角色兼容、`修订 v{version}` 标签与全局关闭 AntD 两字中文按钮自动插空格（`button={{ autoInsertSpace: false }}`），消除 `'详情'` 变成 `'详 情'` 导致交互与 E2E 定位失败（同步更新 `test_31_web_ui_console.py` 使用与同文件 `登\s*录` 一致的正则 `^确\s*定$` 匹配 AntD 确定按钮）。
  2. **移动/平板端溢出与菜单遮挡修复**：
     - 提取 `isNarrowViewport()`（[viewport.ts](frontend/src/shared/lib/viewport.ts)），在 `AdminLayout.tsx` 与 `ConsoleLayout.tsx` 同步初始化移动端侧边栏折叠态，彻底消除 `390×844` 首帧 401px 过渡溢出；
     - 修复 `ConsoleLayout.tsx` 在 `sidebarCollapsed` 为 true 时仍传非空 `openKeys` 导致 AntD 弹出悬浮子菜单浮层遮挡 `/console/tasks` 左上角主按钮的问题（隔离 `collapsedOpenKeys` 并随路由/折叠重置）；
     - 修复 `base.css`（`.app-admin-context` 省略换行）、`responsive.css`（`.resource-list-toolbar` 宽度收敛）与 `AgentPane.tsx` 窄屏布局。
  3. **React / Ant Design 控制台警告清零（全 62 路由 `consoleErrors === []`）**：
     - 全局 59 个 `.tsx` 文件将废弃的 `destroyOnClose` 迁移为 `destroyOnHidden`；
     - 消除 `ModelCenterPage.tsx:653`、`Integration.tsx`、`Projects.tsx`、`AudioPage.tsx`、`JobsPage.tsx`、`TaskCreateModal.tsx`、`VariableRefPanel.tsx` 在未挂载弹窗期间触发 `Form.useForm()` 未连接警告；
     - 修复 `AgentPane.tsx`、`SkillPane.tsx`、`McpPane.tsx` 同级闭态模态框重复 `key="closed"` 警告；
     - 统一 `PageState.tsx`（去除 `<Spin tip>` 非巢状警告）、`Knowledge.tsx`（`Space.Compact` 替代 `addonBefore`）、`FlowSteps.tsx`（`styles={{ body }}` 替代 `bodyStyle`）、`Environments.tsx` 与 `RecycleBinPage.tsx`（补齐 `.page-header`）、`AgentPage.tsx`（补齐 `.page-container`）、`ConsoleLayout.tsx`（`/console/asr/experiments` 面包屑 `'参数对比'` → `'参数实验'`）。
- **对应测试与结果**：`bash scripts/e2e_case_generation.sh` **35 passed, 0 failed（7.4m）**，后端 `test_31_web_ui_console.py` 及全量 `tests` **1312 passed, 0 failed**。

### P2 & CI/CD & 数据库迁移审计
- **CI 流水线（[quality.yml](.github/workflows/quality.yml)）**：重构为 6 阶段完整质量门禁（Stage 1 静态编译 `../deploy` + Ruff + TS + ESLint + Node 单测；Stage 2&3 PostgreSQL 16 + Redis 7 + Playwright Chromium + 单 head 与全量/嵌套 pytest；Stage 4 全量 Playwright E2E 及失败 Trace 上传；Stage 5 Vite Build + 前后端 Docker 构建；Stage 6 `.env` 追踪扫描 + `npm audit --audit-level=high` + 公开分享安全单测）。
- **迁移审计**：检查 `0087_dagu_automation_provider.py`（保留历史数据的单向保护）、`0088_dagu_dispatch_idempotency.py`、`0089_defect_public_share.py`，新增 [test_migration_audit_0089.py](backend/tests/test_migration_audit_0089.py) 验证单 head、索引/外键完整性与可逆版本升降级链路。

---

## 三、遗留与 BLOCKED 项说明（诚实披露）

| 阻塞项 | 原因与影响范围 | 解除条件与下一步操作 |
|---|---|---|
| `backend/integration_tests/test_dagu_integration.py` | 当前仓库未连接可控的隔离 Dagu 测试实例（未设置 `DAGU_INTEGRATION_ENABLED=true`） | 在预发布/测试环境提供受控 Dagu 地址与凭据后执行 `DAGU_INTEGRATION_ENABLED=true pytest -v integration_tests/test_dagu_integration.py`（禁止指向生产 Dagu） |
| `backend/integration_tests/test_feishu_integration.py` | 缺少隔离的测试飞书群机器人 Webhook，禁止向生产业务群推送验证消息 | 配置 `FEISHU_INTEGRATION_ENABLED=true` 与 `FEISHU_TEST_WEBHOOK_URL`/`FEISHU_TEST_SECRET` 后执行联调脚本，验证真实手机/PC 端卡片渲染与跳转 |
| 本地 Docker Hub 镜像重构建 & 离线 `npm audit` / 本地 `ruff` | 本机网络无法连通 `registry-1.docker.io`（TLS EOF）及 npm 官方 audit 接口，且本机 venv 未安装 `ruff` | 推送至 GitHub `develop` 后由 GitHub Actions `quality.yml`（Stage 1 / Stage 5 / Stage 6）自动拉取镜像与运行 `ruff check --exact` 与 `npm audit` |
