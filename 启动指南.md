# 启动指南（前后端本地联调）

测试开发平台 monorepo：后端 FastAPI + PostgreSQL，前端 React + Vite。
本文覆盖**首次初始化**、**日常启动/停止**、**验证**与**常见故障**。
开发任务的分支/提交规范见 `.claude/skills/develop-this-project/SKILL.md`，本文只讲「把服务跑起来」。

## 0. 端口与组件约定

| 组件 | 地址 | 说明 |
|---|---|---|
| PostgreSQL | `127.0.0.1:5432` | 平台主库（可用 `compose.yaml` 起，也可用本机已有实例） |
| 后端 | `http://127.0.0.1:8001` | FastAPI；Swagger 在 `/docs`，健康检查 `/healthz`（**根路径，不带 `/api/v1`**） |
| 前端 | `http://localhost:5173` | Vite dev server；`/api` 原样代理到 8001（**不 rewrite**） |

环境要求：Python 3.11+、Node 20+、PostgreSQL 16。

## 1. 首次初始化（一次性）

### 1.1 起数据库（二选一）

```bash
# 方式 A：用仓库自带的 compose（数据落在 compose 卷里）
docker compose up -d postgres

# 方式 B：用本机已有 PostgreSQL，跳过此步
```

### 1.2 建库

```bash
psql -h 127.0.0.1 -U root -d postgres -c 'CREATE DATABASE testplatform_dev OWNER root;'
psql -h 127.0.0.1 -U root -d postgres -c 'CREATE DATABASE testplatform_test OWNER root;'
```

`testplatform_dev` 是开发库（`.env` 指向它）；`testplatform_test` 是 pytest 专用隔离库，测试会话会自行重建，**不要**往里面放手工数据。

### 1.3 后端依赖与配置

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt   # 只有 requirements.txt，不要 pip install -e .

cp .env.example .env                        # 已有 .env 就跳过
```

编辑 `.env` 至少确认两项：

```bash
DATABASE_URL=postgresql+psycopg://root:fangzhou123@127.0.0.1:5432/testplatform_dev
SECRET_KEY=<足够长的随机串>   # 生成：python3 -c 'import secrets;print(secrets.token_urlsafe(48))'
```

`SECRET_KEY` 缺失或过短时后端**启动即报错**（`RuntimeError: 请设置 SECRET_KEY 环境变量`），这是刻意设计。

### 1.4 建表 + 首个管理员

推荐用种子脚本一步完成（建库 → Alembic 迁移 → 管理员 → 内置环境）：

```bash
cd backend
INIT_ADMIN_USERNAME=admin \
INIT_ADMIN_PASSWORD="$(python3 -c 'import secrets;print(secrets.token_urlsafe(18))')" \
  .venv/bin/python scripts/seed_admin.py
# 终端会打印初始密码，只出现这一次，请立即保存
```

说明：

- 管理员初始化**幂等**：账号已存在则跳过，绝不覆盖历史密码；脚本不内置任何默认密码
- 常用参数：`--drop`（先删库重建，**仅本地调试用**，看清 `--database-url` 再执行）、`--skip-admin`（只建库迁移）、`--database-url`（指定其他库）
- 若是纯手动管理迁移：空库必须先 `.venv/bin/python -m alembic stamp base` 再 `upgrade head`，否则 Alembic 认不出库

### 1.5 前端依赖

```bash
cd frontend
npm install    # 用 npm（有 package-lock.json），不要换 pnpm
```

## 2. 日常启动 / 停止

两个终端各跑一个：

```bash
# 终端 A：后端（--reload 代码改动自动重启）
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8001

# 终端 B：前端
cd frontend
npm run dev
```

停止：两个终端各自 `Ctrl+C`。后端停止时会自动 flush Langfuse 队列并回收数据库连接池。

后端联调别的端口时，前端代理目标可用环境变量覆盖：

```bash
VITE_API_PROXY_TARGET=http://127.0.0.1:8002 npm run dev
```

## 3. 启动后验证

```bash
curl http://localhost:8001/healthz        # → {"status":"ok"}（根路径，不带 /api/v1）
```

浏览器：

- `http://localhost:5173` —— 用 1.4 步的管理员账号登录；管理端 `/admin/*`，用户控制台 `/console/*`
- `http://localhost:8001/docs` —— Swagger UI，Authenticate 按钮可直接登录调试

## 4. 跑测试（可选但建议）

```bash
# 后端全量（走隔离库 testplatform_test，不碰开发库）
cd backend && .venv/bin/python -m pytest tests/ -q

# 前端类型检查 + 生产构建
cd frontend && npm run typecheck && npm run build
```

## 5. 环境变量速查（backend/.env）

| Key | 必需 | 说明 |
|---|---|---|
| `DATABASE_URL` | ✅ | 平台主库连接串 |
| `SECRET_KEY` | ✅ | JWT 签名密钥；缺失启动即失败 |
| `CORS_ORIGINS` | | 逗号分隔（**不是** JSON），默认含 5173 |
| `AUTO_CREATE_SCHEMA` | | 保持 `false`；表结构一律走 Alembic |
| `INIT_ADMIN_USERNAME` / `INIT_ADMIN_PASSWORD` | | 仅 `seed_admin.py` 读取，运行期无作用 |
| `LANGFUSE_ENABLED` 等 5 项 | | Agent LLM 可观测埋点，默认关闭；三环境各用独立 project 的 key，详见下方 |

### Langfuse（Agent LLM 可观测，默认关闭）

三环境隔离约定：**每个环境一个独立 Langfuse project（各一套 key）**，真实 key 只写本机 `.env` 或部署平台环境变量，绝不提交版本库：

```bash
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_BASE_URL=https://cloud.langfuse.com
LANGFUSE_ENVIRONMENT=test        # development / test / production 之一
```

未启用或 key 不齐时埋点全链路 no-op，不影响主流程；trace 在 Langfuse UI 可按 environment 标签过滤。

## 6. 常见故障

| 症状 | 解法 |
|---|---|
| `RuntimeError: 请设置 SECRET_KEY 环境变量` | `.env` 里补上足够长的随机 `SECRET_KEY` 后重启 |
| 500「关系 xxx 不存在」 | 库结构落后：`.venv/bin/python -m alembic upgrade head` |
| 空库跑迁移报 head 冲突 | 先 `alembic stamp base` 再 `upgrade head`（或直接用 1.4 的 seed 脚本） |
| 前端调接口 404 / 代理连不上 | 后端没起在 8001；或 `VITE_API_PROXY_TARGET` 指错端口 |
| `/api/v1/healthz` 返回 404 | 正常——健康检查在根路径 `/healthz`，不带版本前缀 |
| 429「过于频繁」 | 触发限流（登录同 IP 60/分钟、注册同 IP 10/小时）；等窗口过去 |
| 400「验证码错误或已过期」 | 验证码一次性且 300 秒过期，点图片刷新后重试 |
| Langfuse 报 `socksio is not installed` | 本机走 SOCKS 代理时 `pip install socksio`（已在 requirements 中） |
| `npm install` 卡住 | `npm cache clean --force && npm install`，或换 registry |
