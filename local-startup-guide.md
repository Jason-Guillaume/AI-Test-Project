# 本地项目启动指南

更新日期：2026-10-26。

本文说明如何在本机启动 PostgreSQL、FastAPI 后端和 React 前端。仓库的 `compose.yaml` 只启动 PostgreSQL；应用服务分别在终端运行。首次初始化后，日常开发只需启动数据库和前后端。

## 环境要求

- Docker Compose v2，或可连接的 PostgreSQL 16
- Python 3.11 或更新版本
- Node.js 20 或更新版本，以及 npm

本地默认端口：PostgreSQL `5432`、后端 `8001`、前端 `5173`。Compose 仅绑定 `127.0.0.1`，数据库凭据必须由本地环境显式提供。

## 首次初始化

### 1. 启动数据库

在仓库根目录运行：

```bash
export POSTGRES_USER=platform_dev
export POSTGRES_PASSWORD="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')"
export POSTGRES_DB=testplatform_dev
docker compose up -d postgres
docker compose ps
```

等待 PostgreSQL 状态变为 `healthy`。Compose 不含默认用户或密码；上述变量仅保存在当前终端环境。若使用已有 PostgreSQL，请准备一个可创建数据库和迁移表的账号，并在后续配置中替换连接串。

### 2. 安装并配置后端

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
```

编辑 `backend/.env`，至少设置：

```dotenv
DATABASE_URL=postgresql+psycopg://<用户名>:<数据库密码>@127.0.0.1:5432/<数据库名>
SECRET_KEY=<至少 32 个字符的随机密钥>
AUTH_COOKIE_SECURE=false
AUTO_CREATE_SCHEMA=false
```

生成 `SECRET_KEY` 的命令：

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

不要提交 `.env` 或真实密钥。数据库表结构由 Alembic 管理，保持 `AUTO_CREATE_SCHEMA=false`。
密钥不要粘贴到聊天、截图或日志；如果已经分享，建议更换。若已配置模型 API Key 且 `MODEL_CONFIG_ENCRYPTION_KEY` 留空，数据库中的密文使用 `SECRET_KEY` 派生，轮换前需先保留旧值为独立的 `MODEL_CONFIG_ENCRYPTION_KEY`，否则现有模型密钥将无法解密。

### 3. 初始化数据库和管理员

仍在 `backend/` 目录运行。下面会在终端中安全读取管理员密码，输入时不回显：

```bash
export INIT_ADMIN_USERNAME=admin
printf '请输入本地管理员密码（输入不回显）: '
read -rs INIT_ADMIN_PASSWORD
printf '\n'
export INIT_ADMIN_PASSWORD
.venv/bin/python scripts/seed_admin.py
unset INIT_ADMIN_USERNAME INIT_ADMIN_PASSWORD
```

脚本会检查并创建目标数据库、执行 Alembic 最新迁移、写入内置环境并尝试创建管理员。账号已存在时会跳过，不会重置密码；请自行保存首次设置的密码。仅本地临时数据库可使用 `--drop` 重建，运行前务必确认 `DATABASE_URL` 指向的库可以删除。

以后拉取了包含新迁移的代码，可在 `backend/` 下运行：

```bash
.venv/bin/python -m alembic upgrade head
```

### 4. 安装前端依赖

```bash
cd ../frontend
npm install
```

## 日常启动

打开三个独立终端，并让每个终端都从仓库根目录开始；下列 `cd backend` / `cd frontend` 命令都以根目录为起点。不要在已经切到 `frontend/` 的终端里直接执行 `cd backend`。

**终端一：数据库**（若尚未启动）：

```bash
docker compose up -d postgres
```

**终端二：后端**：

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

**终端三：前端**：

```bash
cd frontend
npm run dev
```

打开 [http://localhost:5173](http://localhost:5173)，使用初始化时设置的账号登录。管理端位于 `/admin`，用户控制台位于 `/console`。Vite 默认把 `/api` 请求原样代理到 `http://127.0.0.1:8001`；后端端口不同时，可在启动前端时设置 `VITE_API_PROXY_TARGET`。

## 验证服务和运行检查

```bash
curl http://127.0.0.1:8001/healthz
```

健康检查应返回 `{"status":"ok"}`；它只确认进程存活，不检查数据库依赖。Swagger 文档位于 [http://127.0.0.1:8001/docs](http://127.0.0.1:8001/docs)，不带 `/api/v1` 前缀。

可选验证命令：

```bash
# 后端全量测试：会创建并在结束后删除独立的 testplatform_test-p<PID> 数据库。
# 需要 TEST_POSTGRES_* 配置的 PostgreSQL 账号具备创建和删除数据库的权限。
(cd backend && .venv/bin/python -m pytest -q tests/)

# 前端检查和生产构建
(cd frontend && npm test && npm run lint && npm run typecheck && npm run build)
```

后端测试需显式设置 `TEST_POSTGRES_PASSWORD`，并确保测试账号有创建、删除隔离测试库的权限；不要指向生产或含重要数据的数据库。

## 停止服务

后端和前端终端分别按 `Ctrl+C`。只停止 PostgreSQL 容器可运行：

```bash
docker compose stop postgres
```

`docker compose down` 默认保留数据库卷；`docker compose down -v` 会删除卷和其中的本地数据。

## 常见问题

| 现象 | 检查项 |
|---|---|
| 后端提示 `SECRET_KEY` 未配置 | 检查 `backend/.env` 是否存在且已设置随机长密钥，然后重启后端。 |
| `zsh: no such file or directory: .venv/bin/uvicorn` | 当前目录不是 `backend/`；若在 `frontend/`，先运行 `cd ../backend`，再启动后端。 |
| 数据库认证失败 | 核对 Compose 的 `root/fangzhou123` 与 `.env` 的 `DATABASE_URL`；自建数据库则使用自己的账号密码。 |
| 迁移后仍提示表或字段不存在 | 在 `backend/` 执行 `.venv/bin/python -m alembic upgrade head`。 |
| 前端 API 请求失败或代理报错 | 确认后端监听 `8001`；其他端口需设置 `VITE_API_PROXY_TARGET`。 |
| 访问 `/api/v1/healthz` 返回 404 | 这是预期行为；健康检查地址是根路径 `/healthz`。 |
| 本机 `5432` 已占用 | 停止冲突的 PostgreSQL，或修改 Compose 端口映射，并同步更新数据库连接和测试环境变量。 |

模型服务、Langfuse 和 ZAP 是可选能力；需要使用时再在管理页或环境配置中单独设置，不是启动主站的前置条件。更完整的数据库、环境变量和联调说明见 [docs/getting-started.md](docs/getting-started.md)。
