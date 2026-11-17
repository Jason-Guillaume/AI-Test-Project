# 缺陷免登录分享与飞书研发协同

缺陷分享改动与 Dagu 整改已整合到同一项目。

## 1. 现有缺陷管理复用

- 缺陷表、状态枚举和 `DefectService.create_bug` / `update_bug` / `delete_bug` 没有重写。
- 公开提交走新增的 `DefectService.apply_external_repair`。它只把状态写成「已修复」，并复用 `notify()` 通知报告人和处理人。
- 已关闭、已拒绝不能被公开链接修改。已经是已修复时不新增状态记录。
- 测试人员仍用原有缺陷更新：详情里的「验证通过，关闭缺陷」和「验证失败，重新处理」调用原来的 `PUT /bugs/{bug_id}`。
- 创建缺陷不会自动推送飞书。
- 缺陷模型没有独立的预期结果、实际结果列。勾选这两项时公开页显示「未记录」，没有从描述里猜测。
- 缺陷和 Agent 执行、Allure 文件没有现成外键。勾选这两项时返回空，不暴露服务器路径。

## 2. 飞书通知复用

- 发送仍走 `FeishuNotificationService`。HTTP 投递抽成 `_deliver()`，`send_card()` 继续给报告和自动化通知使用。
- 渠道仍是项目里的 `NotificationChannel`，不要求重新填写 Webhook。
- 卡片方法是 `build_defect_share_card()`，放在现有 `card_builder.py`。
- 正文先脱敏，分享 URL 在脱敏之后写入。入库的 `request_snapshot` 仍会掩掉凭证。
- 发送失败只记 `NotificationRecord.status=FAILED`，不删除缺陷和分享。
- 同一条分享失败后重试不新建分享行。客户端还持有凭证时原样重发；历史里的「重新推送」会轮换哈希，因为数据库没有明文。

## 3. 数据库和迁移

迁移：`backend/alembic/versions/0089_defect_public_share.py`，`down_revision = 0088`（Dagu 迁移）。

- 新表 `defect_share_link`：公开 `share_id`、凭证 SHA-256、字段白名单、内容快照、有效期、撤销和归档时间、查看次数。
- 新表 `defect_external_action`：外部修复说明、版本、Commit、自报姓名、`actor_type=EXTERNAL_SHARE`。同一分享只能有一条 `RESOLVE`。
- `notification_record` 增加可空列：`bug_id`、`share_link_id`、`event_type`、`idempotency_key`、`retry_count`。原有 `report_id` 保留。

旧分享工作树曾将开发库升级到旧版分享 `0088`。合并后的 `0089` 会幂等补齐 Dagu `0088`，再建立缺陷分享结构；升级前应备份数据库并在隔离环境验证。

## 4. 新增 API

内部认证：

- `POST /api/v1/bugs/shares/preview`
- `POST /api/v1/bugs/{bug_id}/shares`
- `POST /api/v1/bugs/shares/batch`
- `GET /api/v1/bugs/{bug_id}/shares`
- `GET /api/v1/bugs/{bug_id}/shares/{share_id}`
- `POST /api/v1/bugs/{bug_id}/shares/{share_id}/revoke`
- `POST /api/v1/bugs/{bug_id}/shares/{share_id}/retry`
- `POST /api/v1/bugs/shares/revoke-batch`
- `POST /api/v1/bugs/shares/archive-expired`（仅平台管理员）

公开、不使用平台 JWT：

- `GET /api/v1/public/defect-shares/{share_id}`
- `POST /api/v1/public/defect-shares/{share_id}/views`
- `POST /api/v1/public/defect-shares/{share_id}/resolve`

GET 不改缺陷状态，也不增加查看次数。查看次数由公开页随后的 POST 写入。

## 5. 前端页面和路由

- 缺陷列表：单条推送、批量推送、已推送标记。
- 缺陷详情：分享历史、撤销、重新推送、外部修复说明、回归关闭或退回处理中。
- 推送弹窗从已有通知渠道读取群聊，并提供字段、有效期、是否允许提交已解决和预览。
- 公开路由：`/public/defects/share/:shareId`。它在登录守卫之外。恢复登录态失败时，如果当前路径以 `/public/` 开头，不会跳到登录页。
- 凭证从 URL Fragment 读取，用 `Authorization: Bearer` 调用独立 axios 实例。

## 6. Token 安全

- `secrets.token_urlsafe(32)`，解码后至少 256 bit。
- 数据库只存 SHA-256。比较使用 `hmac.compare_digest`。
- 明文只在创建或重新签发的响应里返回一次。
- 公开地址形如 `/public/defects/share/{share_id}#token={token}`。
- 错误凭证和未知 `share_id` 都返回「分享链接无效或无权访问」。
- 凭证正确后才区分过期、撤销、已删除和不允许提交。
- 公开接口有独立进程内限流，不改登录/注册那三组限流键。
- 公开 API 响应带 `Cache-Control: no-store`、`Referrer-Policy: no-referrer`、`X-Robots-Tag: noindex, nofollow` 和严格 CSP。
- 生产页面路径 `/public/` 的同类头写在 `frontend/nginx.conf`。页面 CSP 允许同源脚本和样式，API CSP 是 `default-src 'none'`。

## 7. 状态同步

| 操作 | 结果 |
|---|---|
| 开发人员提交已解决 | 缺陷变为「已修复」，写入外部处理记录，并通知报告人和处理人 |
| 重复提交 | 不新增状态记录 |
| 已关闭或已拒绝 | 409，不修改 |
| 测试验证通过 | 原更新接口改为「已关闭」 |
| 测试验证失败 | 原更新接口改为「处理中」 |
| 撤销、过期或归档 | 公开页立即不能访问 |
| 状态变化 | 有效公开页读取实时 `live_status`；其他内容来自推送快照 |

站内通知事件是 `defect.external_resolved`。`actor` 为空，不伪造内部用户。默认不把状态变化再推回飞书群。

## 8. 飞书卡片

卡片包含平台名称、编号、标题、严重度、状态、项目、摘要、复现步骤摘要、创建时间、推送人、有效期和「查看缺陷详情」按钮。批量时每 8 条一张汇总卡，每条缺陷有独立链接。卡片不放请求和响应正文。渠道配置了关键词时，原文附在卡片末尾，供飞书关键词校验使用。

## 9. 测试执行结果

已执行：

- `tests/test_89_defect_public_share.py`：8 通过。
- `tests/test_08_defects.py` 与 `tests/test_17_report_notification.py`：40 通过。
- `frontend`：`npm run typecheck` 通过。

覆盖了凭证哈希、字段隔离、脱敏、过期、撤销、跨链接隔离、修复回写、重复提交、并发提交、关闭后拒绝、只读链接、XSS 文本、查看次数不在 GET 中增加、权限、批量、失败重试、飞书超时、暴力错误凭证限流、软删除和归档。

浏览器打开了 `http://127.0.0.1:5175/public/defects/share/missing-share#token=not-a-valid-token`。页面停在公开路由，没有跳到登录页，并显示「分享链接无效或无权访问」。手机宽度模拟下标题和说明仍在卡片内。没有控制台账号，因此没有在浏览器里点完整的登录后推送流程。

Playwright 用例已写在 `frontend/e2e/defect-public-share.spec.ts`。后续在隔离数据库和真实前后端运行，通过完整的推送、匿名修复、平台查看与回归关闭流程。飞书 Webhook 使用本机测试桩，不代表真实飞书联调通过。

## 10. 安全测试结果

后端测试验证了错误凭证、连续猜测触发 429、公开响应不含 `bug_id` / `project_id`、描述中的 Bearer、密码、绝对路径和数据库连接串被去掉、脚本标签被去掉、公开接口不提供附件目录。请求体字段有长度限制，`Content-Length` 超过 16 KB 的公开写请求会被拒绝。

这些是本地自动化结果，不是外部渗透测试。

## 11. 尚未解决

- 没有真实飞书租户 Webhook，不能声称群里已经收到卡片。单测使用 httpx 桩。
- 未配置 `PUBLIC_APP_BASE_URL` 时，分享地址是相对路径，飞书按钮打不开。
- 预期结果、实际结果、Agent 记录和 Allure 入口受现有数据模型限制，见第 1 节。
- 公开限流只在单个 API 进程内有效。多实例需要在网关再加限制。
- 过期归档是管理员接口，没有单独的定时任务。创建分享不会顺带改其他业务。
- 历史记录里的「重新推送」会签发新凭证并使旧凭证失效。这是不保存明文的结果。
- Playwright 已覆盖主流程，撤销与过期的浏览器流程仍需补充。

## 12. 部署和联调

迁移：

```bash
cd backend
.venv/bin/python -m alembic upgrade head
```

后端：

```bash
cd backend
export SECRET_KEY=...
export PUBLIC_APP_BASE_URL=https://你的平台域名
.venv/bin/uvicorn app.main:app --port 8001
.venv/bin/python -m pytest tests/test_89_defect_public_share.py -q
```

前端：

```bash
cd frontend
npm run dev
npm run typecheck
npm run build
```

飞书：

1. 在项目的「通知渠道」里接入已有飞书自定义机器人 Webhook。不要在推送弹窗里再填一遍。
2. 如果机器人启用了关键词，把关键词填进渠道配置。卡片会带上原文。
3. 设置 `PUBLIC_APP_BASE_URL` 为浏览器可访问的 HTTPS 源站，不能带路径。
4. 反向代理需要把 `/public/` 指到前端，把 `/api/` 指到后端。页面安全头已写在 `frontend/nginx.conf`。
5. 用测试渠道先发一条缺陷。确认群里的按钮能打开 `/public/defects/share/...#token=...`。
6. 开发人员提交已解决后，测试人员在缺陷详情看到修复说明，再执行原测试并把状态改为已关闭。

启动地址请根据实际部署配置；测试使用的临时服务和数据库不属于部署配置。

## 修改文件

后端：

- `backend/alembic/versions/0089_defect_public_share.py`
- `backend/app/features/defects/models/share.py`
- `backend/app/features/defects/schemas_share.py`
- `backend/app/features/defects/services/share_service.py`
- `backend/app/features/defects/services/public_rate_limit.py`
- `backend/app/features/defects/share_router.py`
- `backend/app/features/defects/public_router.py`
- `backend/app/features/defects/services/defect_service.py`
- `backend/app/features/defects/router.py`
- `backend/app/features/defects/schemas.py`
- `backend/app/features/defects/models/__init__.py`
- `backend/app/features/defects/__init__.py`
- `backend/app/platform/notifications/services/feishu_service.py`
- `backend/app/platform/notifications/models/notification_record.py`
- `backend/app/orchestration/report_delivery/card_builder.py`
- `backend/app/core/notifications/notify.py`
- `backend/app/main.py`
- `backend/tests/test_89_defect_public_share.py`
- `backend/tests/test_automation_dagu_migrations.py`

前端：

- `frontend/src/pages/public/DefectShare/index.tsx`
- `frontend/src/pages/public/DefectShare/share.css`
- `frontend/src/features/defects/components/DefectShareModal.tsx`
- `frontend/src/features/defects/components/DefectShareHistory.tsx`
- `frontend/src/features/defects/api/publicShare.ts`
- `frontend/src/features/defects/api/defects.ts`
- `frontend/src/features/defects/contracts.ts`
- `frontend/src/pages/console/Defects/index.tsx`
- `frontend/src/app/App.tsx`
- `frontend/nginx.conf`
- `frontend/e2e/defect-public-share.spec.ts`

## 后续安全修复与验证（2026-11-17）

- 新增 ASGI 请求体限制：公开分享写请求按实际接收的字节计数，超过 16 KiB 在 JSON 解析前返回 413；即使没有 `Content-Length` 或采用分块传输也生效。错误响应保留公开接口安全头。
- 新增 `backend/tests/test_defect_public_body_limit.py`：分块超限、边界值和其他路由隔离共 3 项通过。
- 本次重新运行 `npm run typecheck` 与 `npm run build`，均通过。
- 合并后使用临时隔离 PostgreSQL 运行分享、缺陷、报告通知及 Dagu 迁移回归：55 项通过；旧分享 `0088` 兼容升级专项测试通过。
- 浏览器主流程在隔离环境通过，飞书使用本地测试桩；真实飞书联调仍未完成。

## 合并后的补充

缺陷详情直接显示外部修复说明、提交时间和自报身份。两份未提交改动已整合到当前工作区；迁移图为 `0087 → 0088 Dagu → 0089 缺陷分享`。旧分享版本的 `0088` 升级到 `0089` 的兼容路径已在隔离 PostgreSQL 验证。
