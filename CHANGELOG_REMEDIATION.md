# 工程质量整改变更日志（Changelog of Quality Remediation）

**对比基准**：`develop`（`fe13026`） → **目标分支**：`feature/quality-remediation`  
**说明**：本变更日志记录全部代码修改、配置与环境变量变更、接口契约补充、数据库与生命周期行为变化以及测试/CI 新增内容。

---

## 一、配置与基础设施变更

- **环境变量与配置项**（[backend/app/core/config.py](backend/app/core/config.py)、[backend/.env.example](backend/.env.example)）：
  - 新增 `APP_ENV`（运行环境标识，默认 `development`）、`REDIS_URL`（分布式限流 Redis 连接串）、`TRUSTED_PROXY_CIDRS`（受信任反向代理网段，兼容 IPv4/IPv6）、`PUBLIC_SHARE_RATE_LIMIT_FAIL_CLOSED`（Redis 不可用降级/拒绝策略）、`PUBLIC_SHARE_RATE_LIMIT_SALT`（限流 Key 摘要盐）。
  - 新增 `DEFECT_SHARE_ARCHIVE_ENABLED`（默认 `true`）与 `DEFECT_SHARE_ARCHIVE_INTERVAL_SECONDS`（默认 `86400`，范围 `60..604800`）。
- **依赖与容器编排**：
  - [backend/requirements.txt](backend/requirements.txt)：新增 `redis>=5,<6`。
  - [compose.yaml](compose.yaml)：新增 `redis:7-alpine` 服务及健康检查，并向 `backend` 服务注入 `REDIS_URL`。
  - [backend/Dockerfile](backend/Dockerfile)：强化 `/ms-playwright` 权限与容器内浏览器依赖安装。
  - [scripts/e2e_case_generation.sh](scripts/e2e_case_generation.sh)：设置测试期 `PUBLIC_APP_BASE_URL` 确保完整 URL 推送 E2E 可验收。
- **CI 门禁重构**（[.github/workflows/quality.yml](.github/workflows/quality.yml)）：
  - 升级为 6 阶段质量流水线：`Stage 1` 静态检查（修正 `../deploy` 路径与精确文件名列表）→ `Stage 2 & 3` 后端全量/子模块测试 + Chromium 启动检查 + Alembic 单 head → `Stage 4` 全量 Playwright E2E + 失败产物上传 → `Stage 5` Vite & 前后端容器构建 → `Stage 6` 敏感 `.env` 追踪扫描、`npm audit` 及公开分享安全测试。

---

## 二、接口契约与数据库/生命周期变化

- **接口响应扩展**：
  - [backend/app/features/defects/schemas_share.py](backend/app/features/defects/schemas_share.py) / [frontend/src/features/defects/contracts.ts](frontend/src/features/defects/contracts.ts)：`SharePreviewResponse` / 分享预览契约新增 `public_url_valid: bool = True` 与 `public_url_error: str | None = None`，用于在前端精确提示 `PUBLIC_APP_BASE_URL` 配置错误，拒绝相对路径伪装推送成功。
- **数据库行为与后台生命周期**：
  - **无新建破坏性迁移**，保持 `0089 (head)` 为唯一 head；通过 [test_migration_audit_0089.py](backend/tests/test_migration_audit_0089.py) 验证 `0086→0089`、`0089→0088→0089` 及 `0087` 单向历史数据保护逻辑。
  - [backend/app/main.py](backend/app/main.py)：lifespan 启动时于生产环境下记录 `PUBLIC_APP_BASE_URL` 校验告警，并启动周期归档守护线程 [share_archive_worker.py](backend/app/features/defects/services/share_archive_worker.py)。
  - [backend/app/features/defects/services/share_service.py](backend/app/features/defects/services/share_service.py)：`record_view` 改为原子 SQL 递增防并发丢失计数；访问鉴权补全已软删除缺陷（`Bug.deleted_at`）即时失效校验；抽离幂等 `archive_expired_shares()`。

---

## 三、后端核心业务与安全代码变更

- **身份、组织与项目隔离（P0.3）**：
  - [user_service.py](backend/app/platform/users/services/user_service.py)：恢复 `register()` 与 `create_by_admin()` 同事务调用 `ensure_personal_organization(db, user)`。
  - [management_service.py](backend/app/platform/organizations/services/management_service.py) & [organization_service.py](backend/app/platform/organizations/services/organization_service.py)：恢复用户自主建组织及组织管理员管理本组织（update/candidates/members/transfer），保留删除组织为平台管理员专属；清理冗余局部导入。
  - [project_service.py](backend/app/platform/projects/services/project_service.py) & [roles.py](backend/app/core/security/roles.py)：组织边界校验收敛复用 `require_organization_admin`；全面过滤软删除成员/组织，用户退出组织立即撤销项目可见性，使用去重子查询消除 Dashboard 重复。
  - [module_service.py](backend/app/features/api_catalog/services/module_service.py)：恢复 `delete_module()` 走 `delete_resource("api_module", ...)` 的非空模块 `409 Conflict` 保护。
- **Playwright 浏览器生命周期（P0.2）**：
  - [playwright_executor.py](backend/app/execution/browser/playwright_executor.py) & [session_manager.py](backend/app/execution/browser/session_manager.py)：新增 `chromium_launch_args()` 与 `classify_browser_error()`；为 `_call()` 与 `close()` 补超时释放，保证 `_SLOTS` 永不死锁；按 `session_id` 加 `_OPEN_LOCKS` 防并发双开。
- **缺陷公开分享分布式限流与飞书卡片（P1.4 & P2）**：
  - [public_rate_limit.py](backend/app/features/defects/services/public_rate_limit.py) & [public_router.py](backend/app/features/defects/public_router.py)：基于 Redis Lua 原子滑动窗口支持多维度与错误桶独立限流、HMAC/SHA256 Key 脱敏与自动过期 TTL、多可信代理逆序解析与防伪造 IPv4/IPv6 提取、降级/fail-closed 策略。
  - [card_builder.py](backend/app/orchestration/report_delivery/card_builder.py)：飞书 Markdown 卡片文本转义尖括号及特殊字符并限制字段超长截断。
- **Dagu 自动化执行中心（P1.5）**：
  - [status.py](backend/app/features/automation_center/providers/status.py)、[dagu_client.py](backend/app/features/automation_center/providers/dagu_client.py)、[dagu_provider.py](backend/app/features/automation_center/providers/dagu_provider.py)、[center_service.py](backend/app/features/automation_center/services/center_service.py)、[deploy/dagu/runner.py](deploy/dagu/runner.py)：`NOT_STARTED` → `PENDING`；新增 `_PinnedSyncBackend` 防 DNS Rebinding；补齐 `limit`/`nextCursor` 分页与等待态停止；修复派发超时与并发取消意图覆盖竞态；`runner.py` 增加 `git clone --` 参数注入保护与 `finally` 锁释放。

---

## 四、前端与测试文件变更

- **公开缺陷分享（前端）**：
  - 新增 [shareToken.ts](frontend/src/features/defects/api/shareToken.ts)，重构 [DefectShare/index.tsx](frontend/src/pages/public/DefectShare/index.tsx) 与 [publicShare.ts](frontend/src/features/defects/api/publicShare.ts) 实现零持久化内存凭证、`StrictMode` 幂等及 URL Fragment 立即清理。
  - 更新 [DefectShareHistory.tsx](frontend/src/features/defects/components/DefectShareHistory.tsx) 与 [DefectShareModal.tsx](frontend/src/features/defects/components/DefectShareModal.tsx)：展示新链只读可选框、安全剪贴板复制、旧链接作废提醒、飞书状态反馈及防连点，并在预览区展示 `PUBLIC_APP_BASE_URL` 配置错误信息。
- **布局响应式与 Ant Design 警告全面治理**：
  - 新增 [viewport.ts](frontend/src/shared/lib/viewport.ts)，同步初始化 [AdminLayout.tsx](frontend/src/app/layouts/AdminLayout.tsx) 与 [ConsoleLayout.tsx](frontend/src/app/layouts/ConsoleLayout.tsx) 窄屏折叠态；隔离 `ConsoleLayout` 折叠态子菜单 `collapsedOpenKeys` 防止浮层遮挡主操作按钮；修正 `/console/asr/experiments` 面包屑标题 `'参数对比'` → `'参数实验'`。
  - [AppProviders.tsx](frontend/src/app/providers/AppProviders.tsx)：配置 `button={{ autoInsertSpace: false }}`。
  - [ModelCenterPage.tsx](frontend/src/pages/console/ModelCenterPage.tsx)：修正 `canDiagnoseProject` 角色兼容、`修订 v{version}` 展示，移除未挂载 `Form.useWatch` 与渲染期直接 `getFieldValue`。
  - 修复 59 个 `.tsx` 页面组件的废弃 `destroyOnClose` → `destroyOnHidden`；同步修复 `PageState.tsx`（`<Spin>`）、`Knowledge.tsx`（`Space.Compact`）、`FlowSteps.tsx`（`styles={{ body }}`）、`Environments.tsx` 与 `RecycleBinPage.tsx`（`PageHeader`）、`AgentPage.tsx`（`PageContainer`）、`AgentPane.tsx`/`SkillPane.tsx`/`McpPane.tsx`（消除重复 `key="closed"` 与闭态按需挂载）、`TaskCreateModal.tsx`/`VariableRefPanel.tsx`/`AudioPage.tsx`/`JobsPage.tsx`/`Integration.tsx`/`Projects.tsx`（消除未连接表单 `useForm` 警告）以及 `base.css`/`responsive.css`/`DetailDrawer.tsx`/`RunWorkbenchPage.tsx` 窄屏溢出。
- **新增及更新测试**：
  - 后端新加：`tests/test_browser_lifecycle.py`、`tests/test_79_auth_isolation_lifecycle.py`、`tests/test_89b_defect_share_security.py`、`tests/test_89c_feishu_card_reliability.py`、`tests/test_automation_dagu_remediation.py`、`tests/test_migration_audit_0089.py`、`integration_tests/test_dagu_integration.py`、`integration_tests/test_feishu_integration.py`；更新 `test_platform_admin_management.py`、`test_31_web_ui_console.py`。
  - 前端新增/更新：`frontend/tests/defectShareToken.test.mjs`、`frontend/tests/frontendRoutes.test.mjs`、`frontend/e2e/all-routes-responsive.spec.ts`、`frontend/e2e/data-lifecycle.spec.ts`。
