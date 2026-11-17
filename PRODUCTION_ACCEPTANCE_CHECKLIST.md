# 生产环境部署与验收检查清单（Production Acceptance Checklist）

上线部署或合并入发布分支前，运维与研发负责人须逐项核验以下条目并留存确认记录。

---

## 1. 生产部署前检查（Pre-Deploy Gates）

- [ ] GitHub Actions [quality.yml](.github/workflows/quality.yml) Stage 1 ~ Stage 6 全部绿灯（特别包含离线时未能拉取的 Stage 1 `ruff check`、Stage 5 `docker build` 与 Stage 6 `npm audit --audit-level=high`）。
- [ ] 已确认打包提交不含 `.env`、真实私钥、测试截图残留或 `.idea/` 本地配置。
- [ ] 容器镜像 `testplatform-backend`（`backend/Dockerfile`）与 `testplatform-frontend`（`frontend/Dockerfile`）已构建并验证 `/ms-playwright` 可被运行用户只读/执行访问、Chromium 可在容器内以无头模式启动。

## 2. 环境变量配置检查（[backend/.env.example](backend/.env.example)）

| 变量名 | 生产强制要求 | 校验说明 |
|---|---|---|
| `APP_ENV` | `production` | 启用生产 `PUBLIC_APP_BASE_URL` 强制 HTTPS 域名及公开安全策略 |
| `SECRET_KEY` | 强随机密钥（长度 ≥ 32 字节） | 禁止使用默认/示例值 |
| `DATABASE_URL` | `postgresql+psycopg://...` | 指向生产 PostgreSQL 主库 |
| `AUTO_CREATE_SCHEMA` | `false` | 禁止生产应用启动时自动建表，统一由 Alembic 管控 |
| `AUTH_COOKIE_SECURE` | `true` | 生产 HTTPS 下强制 Cookie `Secure` 属性 |
| `CORS_ORIGINS` | 显式生产前端 HTTPS 域名 | 禁止 `*` 或保留 `localhost` / `127.0.0.1` |
| `PUBLIC_APP_BASE_URL` | 完整 HTTPS 公网域名（如 `https://qa.example.com`） | 缺失、非 HTTPS 或为开发内网地址将禁止飞书外链推送并在启动日志告警 |
| `REDIS_URL` | 生产 Redis 地址（如 `redis://:pass@redis:6379/0`） | 多副本部署下公开限流必需 |
| `TRUSTED_PROXY_CIDRS` | 反向代理真实网段（逗号分隔 CIDR） | 用于从右向左提取真实客户端 IP（兼容 IPv4/IPv6）；留空则不信任 `X-Forwarded-For` |
| `PUBLIC_SHARE_RATE_LIMIT_FAIL_CLOSED` | 按可用性策略设为 `true` 或 `false` | `false` 降级单实例有界滑窗；对防刷强要求可设为 `true` 返回 503 |
| `PUBLIC_SHARE_RATE_LIMIT_SALT` | 独立随机盐（留空则回退 `SECRET_KEY`） | 用于限流 Redis Key 摘要脱敏，避免直接存明文 IP |
| `DEFECT_SHARE_ARCHIVE_ENABLED` | `true` | 开启过期公开分享链接自动扫描归档 |
| `DEFECT_SHARE_ARCHIVE_INTERVAL_SECONDS` | `86400`（默认每天，范围 `60..604800`） | 周期执行过期归档任务 |
| `DAGU_ALLOW_INSECURE_HTTP` | `false` | 仅限受控私网且配合 `DAGU_PRIVATE_HOST_ALLOWLIST` 明确允许才开启 |
| `PLAYWRIGHT_NO_SANDBOX` | 容器/无特权命名空间按需配置 | Linux root/容器环境自动附带 `--no-sandbox --disable-setuid-sandbox` |

## 3. 数据库迁移与备份策略（Alembic `0087 ~ 0089`）

- [ ] **升级前备份**：执行迁移前必须完成 PostgreSQL 全库逻辑/物理快照备份（`pg_dump -Fc`）并在测试库试恢复确认可用。
- [ ] **迁移顺序**：确认单一 head：`python -m alembic heads` 输出 `0089 (head)`，再执行 `python -m alembic upgrade head`。
- [ ] **重点版本检查**：
  - `0087_dagu_automation_provider.py`：清理 Jenkins 字段并保留历史运行归档数据，存在 Dagu/LEGACY 数据时内置 `_unsafe_downgrade_reason()` 单向保护，**禁止在有生产数据的库直接执行 `downgrade`**；
  - `0088_dagu_dispatch_idempotency.py`：新增 `dispatch_state` 与 `automation_execution_idempotency` 幂等约束；
  - `0089_defect_public_share.py`：新增 `defect_share_link`、`defect_external_action` 及 `notification_record` 外键与唯一索引。
- [ ] **迁移后验证**：检查关键表索引存在性、`alembic current` 指向 `0089 (head)`，应用 `/healthz` 与 `/readyz` 返回就绪。

## 4. Redis 分布式限流验收

- [ ] 生产 Redis 实例可用，延迟与连接池正常；`compose.yaml` 中已附带 `redis:7-alpine` 健康检查参考配置。
- [ ] 在测试压测下确认 `view`、`resolve` 与 `failure` 错误凭证桶在多个后端副本间共享计数（键带固定 TTL，不会无限增长，不含明文 Token 或明文敏感信息）。

## 5. Dagu 自动化执行中心验收（需外部隔离实例）

- [ ] **配置鉴权与加密**：仅平台管理员可维护 Dagu 集成配置，API Key 落库加密且日志不打印明文凭据。
- [ ] **网络安全边界**：确认目标 Dagu 地址符合 SSRF 与 `_PinnedSyncBackend` DNS 防重绑定约束（若部署在私网需显式列入 `DAGU_PRIVATE_HOST_ALLOWLIST`）。
- [ ] **真实环境联调（当前标注 `BLOCKED`）**：使用受控隔离 Dagu 测试环境执行：
  ```bash
  DAGU_INTEGRATION_ENABLED=true DAGU_BASE_URL=<隔离Dagu地址> DAGU_API_KEY=<测试密钥> \
    .venv/bin/python -m pytest -v integration_tests/test_dagu_integration.py
  ```
- [ ] 核对触发、排队/等待态取消、超时收敛、日志回传及 Allure 报告回链状态完全一致，Runner 权限与工作目录受限。

## 6. 飞书推送与公开分享验收（需隔离测试群）

- [ ] **公网 URL 检查**：调用分享预览接口验证 `public_url_valid === true`，生成的卡片跳转链接为完整 `https://.../#<token>`（Token 位于 Fragment，不进服务端 Query 日志）。
- [x] **真实测试群联调（已基于提供测试机器人 Webhook 通过，切换生产/新测试群时附带签名再复核）**：使用隔离测试群 Webhook 验证：
  ```bash
  FEISHU_INTEGRATION_ENABLED=true FEISHU_TEST_WEBHOOK_URL=<测试群Webhook> FEISHU_TEST_SECRET=<签名密钥> \
    .venv/bin/python -m pytest -v integration_tests/test_feishu_integration.py
  ```
- [ ] 在目标手机/桌面飞书客户端实测点击卡片进入公开分享页后，确认地址栏 Hash 被立即清除，刷新后不会从 LocalStorage 泄漏凭证而是清晰引导重新通过链接打开，外部修复提交后缺陷状态正常推进为 `已修复` 并留存审计。

## 7. Nginx、HTTPS 与安全配置（[frontend/nginx.conf](frontend/nginx.conf)）

- [ ] Nginx 所有非 API 前端子路由返回 `index.html`（`try_files $uri $uri/ /index.html`），任意页面浏览器直接刷新不出现 `404`。
- [ ] `/public/` 路径响应头强制注入：`Cache-Control: no-store`、`Referrer-Policy: no-referrer`、`X-Robots-Tag: noindex, nofollow`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY` 与严格 `Content-Security-Policy`。
- [ ] 上游 TLS 终止反代透传 `X-Forwarded-For` 与 `X-Forwarded-Proto`，且其出口网段已准确写入 `TRUSTED_PROXY_CIDRS`。

## 8. 备份、恢复与发布回滚策略

- **定时备份**：生产 PostgreSQL 配置每日全备 + WAL 归档；ASR/自动化报告持久卷随发布同步快照。
- **应用层回滚**：若新版本应用出现缺陷，优先保留数据库结构（因 `0088`/`0089` 为向后兼容增量表结构且 `0087` 含历史数据保护），仅回滚应用与前端容器镜像版本。
- **数据库回滚**：仅在确认无新数据写入或故障由迁移引起时，**先停止写流量并从升级前 `pg_dump` 备份整体恢复库快照**，严禁在生产环境盲目对包含真实业务数据的 `0087` 以上库执行裸降级。
