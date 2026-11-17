# 回归测试与质量基线对比报告

**执行环境**：macOS（Python 3.14.5 / Node.js / Docker PostgreSQL 16 + Redis 7-alpine / Chromium headless）  
**测试基准分支**：`feature/quality-remediation`（所有最终代码编辑完成后的全量实测结果）

---

## 一、全量回归结果总览

| 检验项目 | 执行命令 | 历史参考基线 | 本机初始基线（`fe13026`） | 整改后最终实测结果 | 状态 |
|---|---|---|---|---|---|
| 后端主测试套件 | `pytest -q tests`（独立 PG 库） | 1237 passed / 42 failed / 6 errors | 1272 passed / 7 failed / 6 errors | **1312 passed, 0 failed, 0 errors**（654.56s） | PASS |
| 后端嵌套业务模块测试 | `pytest -q app/platform/organizations/tests app/features/api_catalog/tests app/features/asr_evaluation/tests app/features/test_management/tests` | 未单列 | 纳入后续全量检查 | **120 passed, 0 failed, 0 errors**（12.79s） | PASS |
| 飞书真实机器人联调 | `FEISHU_INTEGRATION_ENABLED=true pytest -v integration_tests/test_feishu_integration.py` | 无 | 无 | **1 passed（2.06s，`open.feishu.cn` 返回 `code: 0`；常规无开关运行按设计跳过）** | PASS |
| Dagu 真实外部集成测试 | `pytest -rs integration_tests/test_dagu_integration.py` | 无 | 无 | **1 skipped（env-gated `BLOCKED`：缺隔离 Dagu 实例）** | BLOCKED |
| Python 字节码编译 | `python -m compileall -q app tests integration_tests ../deploy` | — | 未校验 `deploy` | **exit 0（全树无语法错误）** | PASS |
| Alembic 迁移头检验 | `python -m alembic heads` | 存在分叉/未审计风险 | `0089` | **`0089 (head)`（唯一 head）** | PASS |
| 前端 Node 单元测试 | `cd frontend && npm test` | 40 passed / 1 failed | 40 passed / 1 failed | **51 passed, 0 failed**（2.51s） | PASS |
| 前端 TypeScript 检查 | `cd frontend && npm run typecheck` | — | 通过 | **exit 0（`tsc -b --noEmit`）** | PASS |
| 前端 ESLint 检查 | `cd frontend && npm run lint` | — | 通过 | **exit 0（`--max-warnings=0`）** | PASS |
| 前端 Vite 生产构建 | `cd frontend && npm run build` | 未完成有效验收 | 未验收最终整改包 | **exit 0（6.42s，`dist/` 产出正常）** | PASS |
| 全量 Playwright E2E | `bash scripts/e2e_case_generation.sh` | 30 passed / 5 failed | 31 passed / 4 failed | **35 passed, 0 failed（7.4m）** | PASS |
| 密钥文件追踪检查 | `! git ls-files \| grep -E '(^\|/)\.env($\|\.)' \| grep -vE '\.(example\|development)$'` | — | 未自动化门禁 | **exit 0（无隐私 `.env` 入库）** | PASS |
| Docker Hub 镜像重拉重建 | `docker build -f frontend/Dockerfile ...` | 未验证最新 | earlier 阶段构建过 | **受离线网络无法连接 `registry-1.docker.io`（EOF）阻塞** | BLOCKED |
| `npm audit` 在线检查 | `npm audit --audit-level=high` | — | — | **受离线 TLS 连接断开阻塞（交 CI Stage 6 执行）** | BLOCKED |

---

## 二、后端测试分项明细（实测 1312 + 120 = 1432 passed）

### 2.1 原失败/错误用例修复后验证（100% 通过）
- **基线 `test_02_auth_flow.py`（1 failed → 全过）**：`test_register_creates_user_and_personal_organization`
- **基线 `test_05_isolation.py`（6 setup errors → 全过）**：
  - `test_owner_can_see_only_own_projects`
  - `test_cross_organization_access_returns_404`
  - `test_viewer_can_read_but_not_write`
  - `test_org_member_sees_org_projects_but_not_others`
  - `test_cross_org_member_addition_is_forbidden_even_for_platform_admin`
  - `test_leftover_cross_org_member_row_stays_invisible`
- **基线 `test_06_persistence.py`（4 failed → 全过）**：
  - `test_users_and_members_are_persisted`
  - `test_deleting_user_preserves_owned_data_and_links`
  - `test_deleting_user_without_successor_keeps_private_data_recoverable`
  - `test_dashboard_my_projects_is_deduplicated`
- **基线 `test_74_user_lifecycle.py`（1 failed → 全过）**：`test_user_purge_preview_protects_project_and_org_references`
- **基线 `test_api_catalog.py`（1 failed → 全过）**：`test_module_crud_two_level_and_default`

### 2.2 新增与专项回归测试明细
- **权限与生命周期扩展**（[test_79_auth_isolation_lifecycle.py](backend/tests/test_79_auth_isolation_lifecycle.py)、[test_platform_admin_management.py](backend/app/platform/organizations/tests/test_platform_admin_management.py)）：组织管理员边界、退组立即收回可见性、Owner/Editor/Member/Viewer 分级矩阵、注册事务原子回滚。
- **Playwright 浏览器环境与生命周期**（[test_browser_lifecycle.py](backend/tests/test_browser_lifecycle.py) + `test_30` ~ `test_35`）：容器 launch args、缺失 Chromium/依赖分类报错、超时与异常下 `_SLOTS` 必释放、挂死关闭超时、同会话并发打开单槽序列化、`test_real_console_create_confirm_debug_report` 全过。
- **缺陷公开分享安全测试**（[test_89_defect_public_share.py](backend/tests/test_89_defect_public_share.py) + [test_89b_defect_share_security.py](backend/tests/test_89b_defect_share_security.py)）：随机令牌散列存储、字段白名单、暴力猜测/错误桶独立限流、Redis 7-alpine 多实例原子计数与 TTL、IPv4/IPv6 可信反代链与 `X-Forwarded-For` 伪造拒绝、Redis 不可用降级与 fail-closed 模式、重推旧链立即作废及失败审计、定时自动归档幂等性及重跑、已删缺陷立即失效、`PUBLIC_APP_BASE_URL` 生产校验、请求体大小上限、跨项目/并发提交防护。
- **飞书卡片可靠与脱敏测试**（[test_89c_feishu_card_reliability.py](backend/tests/test_89c_feishu_card_reliability.py)、[test_feishu_integration.py](backend/integration_tests/test_feishu_integration.py)）：中文、尖括号/脚本转义、超长正文边界截断、裸 `Bearer`/三段式 JWT 脱敏、HMAC 签名、超时重试与幂等键保护，并经隔离测试群真实 Webhook 实测投递交互式缺陷卡片与 `build_report_card` 均返回 `code: 0`。
- **Dagu 执行中心专项**（[test_automation_dagu_remediation.py](backend/tests/test_automation_dagu_remediation.py) + `test_automation_dagu_service.py` + `test_78_automation_center.py`）：v2.26.0 状态映射、分页游标、`_PinnedSyncBackend` 防 DNS 重绑定与私网直连拦截、等待态停止与 `/openapi.json` 404 降级、派发超时/取消意图竞态保护。
- **数据库迁移专项**（[test_migration_audit_0089.py](backend/tests/test_migration_audit_0089.py) + `test_automation_dagu_migrations.py` + `test_57_organization_recycle_bin_migration.py`）：单 head `0089`、`0086→0089` 升级与索引约束验证、`0089→0088→0089` 降级与重升幂等性。

---

## 三、前端与 Playwright E2E 测试明细

### 3.1 Node 单元测试（51 passed, 0 failed）
- [frontendRoutes.test.mjs](frontend/tests/frontendRoutes.test.mjs)：路由树 AST 校验、70 既有路由及新增路由显式登记、权限守卫、公开分享免登录顶层访问、Nginx SPA fallback 配置校验。
- [defectShareToken.test.mjs](frontend/tests/defectShareToken.test.mjs)：StrictMode 重挂载防丢失、即时清理 URL Fragment、零持久化/零日志/零 URL query 泄露、重新签发覆盖与失效清理。
- 原有辅助函数与主题 CSS 单测全部保持通过。

### 3.2 Playwright E2E（35 passed, 0 failed，全实栈执行）
- `all-routes-responsive.spec.ts`（2 passed）：
  - **62 条前端业务与异常路由 × 6 个视口**（`1920×1080`、`1440×900`、`1366×768`、`1024×768`、`768×1024`、`390×844`，共 372 次页面状态校验）：零横向溢出、零 JS/React/AntD 控制台告警（仅有向未造数据详情 ID 返回的 `/api/v1/*` 403/404 归入 `expectedBusinessErrors`）、主操作按钮 100% 处于视口内且无浮层遮挡。
  - **11 个代表性管理与工作台页面 × 4 个视口**全屏渲染与截图完成。
- `case-generation.spec.ts`（14 passed）、`data-lifecycle.spec.ts`（12 passed）、`defect-public-share.spec.ts`（1 passed）、`generation-async.spec.ts`（3 passed）、`model-center.spec.ts`（1 passed）、`skill-workspace.spec.ts`（2 passed）：全数真实 Postgres + 隔离 Uvicorn + Vite + Chromium 通过。

---

## 四、失败与跳过用例明细

- **当前环境失败用例数**：`0 failed`、`0 errors`（前后端主线、飞书真实测试群联调及 E2E）。
- **受外部环境阻塞跳过（`BLOCKED`）**：
  1. `backend/integration_tests/test_dagu_integration.py::test_live_dagu_connectivity_and_dag_contract`（需设置 `DAGU_INTEGRATION_ENABLED=true`、`DAGU_BASE_URL`、`DAGU_API_KEY`）
