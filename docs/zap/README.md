# OWASP ZAP 部署与验证（Security Testing Phase 2）

本阶段平台**不内置** ZAP，只通过 REST API 调用外部实例。平台一侧的全部行为见
[Security Testing Phase 2 OWASP ZAP 集成交付报告.md](Security%20Testing%20Phase%202%20OWASP%20ZAP%20集成交付报告.md)。

> ## ⚠️ 先读：本阶段的验证边界
>
> **代码从未在真实 ZAP 实例上跑过。** 开发环境没有 Docker daemon，Phase 2 的
> 全部 97 个后端单测都跑在仓库自带的 Mock 连接器
> （[backend/app/features/security_testing/zap/mock.py](../../backend/app/features/security_testing/zap/mock.py)）上。
>
> 这意味着两件事：
>
> 1. 本文里所有关于**镜像参数、ZAP 版本行为**的说明都是**待部署方核对**的，
>    不是已验证事实；
> 2. 平台连接器对 ZAP 响应形态的假设（尤其是 `/JSON/core/about` 的字段名）
>    **可能**与真实 ZAP 不符。第一次跑真实 ZAP 前请先跑
>    [zap_smoke_check.sh](zap_smoke_check.sh)，它会专门检查这一点。
>
> 部署验证结果必须回填到交付报告的「真实 ZAP 验证」一节，不能由平台一侧代替勾选。

---

## 1. 版本与镜像固定

- 镜像：`owasp/zap2docker-stable`（官方镜像）。
- 平台最低版本要求：**ZAP ≥ 2.12.0**
  （`backend/app/features/security_testing/zap/connector.py` 的
  `MIN_SUPPORTED_VERSION_TEXT`；低于该版本会在连接阶段直接拒绝，报
  「ZAP 版本不受支持」）。

**固定方式**：`stable` 是浮动 tag，同一部署时间在不同机器上可能拉到不同构建。
上线时必须记录实际使用的镜像版本与摘要，写入交付记录：

```bash
docker pull owasp/zap2docker-stable
docker image inspect owasp/zap2docker-stable --format '{{.RepoTags}} {{.Id}}'
```

如果 CI/CD 环境不允许浮动 tag，请改为固定到具体版本 tag，并用
`docker manifest inspect` 记录摘要。**本阶段没有在真实镜像仓库上核对过任何
具体 tag 是否存在**——固定到哪个 tag 由部署方按当时的镜像清单决定。

> 建议同时开启 ZAP 的 API Key（该镜像以环境变量开启，具体变量名与取值
> 请以镜像官方 README 的**当前**说明为准，这里不写死以免写错）。
> 平台的 API Key 只存 Fernet 密文，见下文第 3 节。

---

## 2. 网络隔离（安全红线）

**ZAP 管理 API 绝不能对公网开放**（需求 §三十四）。ZAP 的 API 没有登录态，
一旦暴露在公网，任何人都可以借你的实例去扫描别人。两种部署形态二选一：

### 形态 A：ZAP 与平台后端同处私有网络（推荐）

```yaml
# docker-compose.yml 片段
services:
  zap:
    image: owasp/zap2docker-stable
    restart: unless-stopped
    networks: [zapnet]        # 私有 bridge 网络
    # 注意：这里刻意**没有** ports: —— API 不发布到宿主端口
    healthcheck:
      test: ["CMD-SHELL", "true"]
  backend:
    # 你的后端服务
    networks: [zapnet]
    environment:
      ZAP_ENABLED: "true"
      ZAP_BASE_URL: "http://zap:8090"

networks:
  zapnet:
    driver: bridge
```

### 形态 B：平台后端跑在宿主机

只能把端口绑定到**回环**，不能绑到 `0.0.0.0`：

```bash
# -p 127.0.0.1:8090:8090 —— 只在本机可访问，不对外
docker run -d --name zap \
  -p 127.0.0.1:8090:8090 \
  owasp/zap2docker-stable
```

> 反向检查：`ss -ltnp | grep 8090` 应该只看到 `127.0.0.1:8090`，
> 看到 `0.0.0.0:8090` 就是配置错了。

---

## 3. 平台侧配置

完整键值见 [backend/.env.example](../../backend/.env.example) 的 ZAP 段。
关键项：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `ZAP_ENABLED` | `false` | **默认关闭**。false 时任务会登记为待执行但永不运行，健康检查返回不可用 |
| `ZAP_BASE_URL` | 空 | ZAP REST API 地址 |
| `ZAP_API_KEY_ENCRYPTED` | 空 | 只能是 Fernet 密文，**禁止明文** |
| `ZAP_API_KEY_MODE` | `header` | `header` 走 `X-ZAP-API-Key`；`query` 走 `apikey=`（不推荐，会进日志） |
| `ZAP_VERIFY_TLS` | `true` | 不建议关闭 |
| `ZAP_MAX_CONCURRENT_JOBS` | `1` | 第一版单实例保持 1：同一 ZAP 实例同一时刻只执行一个需修改全局配置的任务 |
| `ZAP_REQUEST_BUDGET` | `5000` | 单次扫描请求预算上限 |
| `ZAP_MAX_JOB_DURATION_SECONDS` | `7200` | 单任务硬上限 |

### 生成 API Key 密文

密文与 `SECRET_KEY` 绑定，换 `SECRET_KEY` 后必须重新加密：

```bash
cd backend
.venv/bin/python -c "from app.shared.crypto import encrypt_secret; print(encrypt_secret('你的ZAP-API-KEY'))"
```

把输出填进 `ZAP_API_KEY_ENCRYPTED`。

---

## 4. 部署顺序

1. 起 ZAP 容器，确认容器内 API 可达（见第 2 节的网络检查）。
2. **跑冒烟脚本**（见第 5 节），确认契约无冲突。
3. 设 `ZAP_ENABLED=true`、`ZAP_BASE_URL`、`ZAP_API_KEY_ENCRYPTED`。
4. 起平台后端，访问 `GET /api/v1/security/zap/health`（需平台管理员）。
   应返回 `enabled=true`、`available=true`、`reachable=true`、
   `api_key_configured=true`（配了密钥时）。

   ⚠️ 两个容易误读的字段，务必知道：
   - `version` **恒为 `null`**。health 端点不发起任何网络请求，
     版本只从下一步的 `capabilities` 端点拿。
   - `reachable` **不表示网络真的通了**。它的取值是
     `ZAP_ENABLED and ZAP_BASE_URL 非空`，只是「配置齐了」，
     不会去连一次 ZAP。真正验证连通性要跑第 5 节的脚本。
5. 访问 `GET /api/v1/security/zap/capabilities`。这一端点**会真的连 ZAP**。
   确认 `version` 有值且 `≥ 2.12.0`、`available=true`，且
   `spider` / `passive` / `active` / `history` 均为 `supported=true`；
   缺任何一个都会在扫描的 PREPARING 阶段以 `ZAP_PLUGIN_MISSING` 失败。
6. 跑一次端到端冒烟（见第 5 节最后一段清单）。
7. 把结果回填交付报告。

---

## 5. 验证

### 5.1 ZAP 侧冒烟脚本

```bash
export ZAP_BASE_URL="http://127.0.0.1:8090"
export ZAP_API_KEY="可选"          # ZAP_API_KEY_MODE=header 时走 X-ZAP-API-Key
./docs/zap/zap_smoke_check.sh
WITH_WRITES=1 ./docs/zap/zap_smoke_check.sh   # 额外做写入型探针（需 ZAP 独占）
```

每项分三态，**HTTP 200 不等于成功**——ZAP 对未知方法与缺参数也返回 200 并带
`{"error": "..."}`：

- `OK`：200 且无 `error` 键
- `PARAMS`：200 但响应含 `error` 键（端点存在，参数或前置条件不满足）
- `ERROR`：非 200 / 连接失败

⚠️ 脚本重点检查一个**已知风险**：平台连接器读的是
`/JSON/core/about` 响应里的 `version` 字段
（`connector.py` 的 `_about()`）。真实 ZAP 的这个端点很可能返回
`zap` 字段而不是 `version`。如果脚本报

```
ERROR  响应用 "zap" 而非 "version" 承载版本：需修 connector._about()，不要改本脚本
```

那就是**代码契约不匹配**，不是部署问题——改 `_about()` 让它同时读两个字段，
并补一条单测，然后回填交付报告。

> 本脚本的三态判定逻辑已用一个本地假 ZAP 跑通过（覆盖 OK / PARAMS / ERROR
> 三种形态、以及 `zap` 字段变体），但**它从未对真实 ZAP 跑过**。

### 5.2 平台侧端到端冒烟

需要一个**已授权的非生产测试目标**。发起一次**被动**扫描后，逐条确认：

1. 任务能从 `PENDING` 走到 `COMPLETED`（或明确失败且给出可读错误码）；
2. `GET .../scan-jobs/{id}/progress` 的进度与阶段单调推进；
3. `GET .../scan-jobs/{id}/alerts` 返回的告警带 `rule_id`，且
   `severity` 与 `confidence` 是两个独立字段、没有被混用（§十八）；
4. `GET .../scan-jobs/{id}/findings` 里的每条都是 **Potential Finding**
   （`POTENTIAL`），没有任何一条被直接判定为确认漏洞（§十八）；
5. `GET .../scan-jobs/{id}/coverage` 里的 URL 已脱敏，不含 `token` / `cookie`
   值（§二十一、§三十四 第 8 条）；
6. 任务事件表（`GET .../scan-jobs/{id}/events`）里**没有**任何明文 JWT、
   Cookie 或 ZAP API Key；
7. 主动扫描在**没有人工批准说明**时返回 403，且有任务被拒绝的审计痕迹。

---

## 6. 已知限制（Phase 2 明确不做）

1. **内网目标扫描不到。** 为了防 SSRF，`scope_guard.is_reachable_public_ip`
   只放行解析到公网地址的目标；`10.x` / `192.168.x` / `172.16-31.x`
   等私网与保留地址一律拒绝（创建扫描目标时就会 403）。
   代价是「授权的内网测试环境」这个场景一期覆盖不到。
   正确的解法是新增「授权私网段白名单」，**不要**为了覆盖内网而放宽
   `is_reachable_public_ip`。
2. **不做支付 / 删除 / 批量修改类主动扫描的二次授权。** Phase 2 对高危动作
   直接拒绝（`scope_guard.BLOCKED_ACTIVE_ACTIONS`），没有实现「二次授权」流程。
3. **不做飞书扫码等人工登录的自动化。** `auth_mode=MANUAL` 时会如实标记
   「无法验证」，不会把无法复现的认证过程记为成功（§十三）。
4. **不把 ZAP 告警当确认漏洞。** 所有告警先落 Potential Finding，人工确认
   状态不会被重扫重置（§十九）。
5. **不实现大规模调度。** `ZAP_MAX_CONCURRENT_JOBS=1`，单实例串行。

---

## 7. 回滚

1. `ZAP_ENABLED=false`（任务登记但永不运行，健康检查如实返回不可用）；
2. 需要彻底隔离时移除 `ZAP_BASE_URL` / `ZAP_API_KEY_ENCRYPTED`；
3. 已登记的任务按正常取消流程处理（`POST .../scan-jobs/{id}/cancel`，
   只置位 `cancel_requested`，由 Worker 在下一个检查点停止）；
4. 数据库迁移是**新增**的（`backend/alembic/versions/0013_zap_security_scan.py`），
   回滚代码不需要回滚表结构。
