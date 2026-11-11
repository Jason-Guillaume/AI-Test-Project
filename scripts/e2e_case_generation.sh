#!/usr/bin/env bash
# 用例生成审核闭环 E2E 编排脚本。
#
# 在**独立隔离库**（默认 testplatform_e2e_gen）上从零开始：建库 → Alembic 升到 head（含 0047-0049）
# → 管理员初始化 → 起 LLM 桩服务器（确定性响应，不访问外部模型、不消耗真实 Token）
# → 起后端 :8101 → 通过真实 API 种入指向桩服务器的启用默认模型配置
# → 起前端 Vite :5174 → Playwright 真实浏览器验收 → 退出清理。
#
# 用法：
#   bash scripts/e2e_case_generation.sh              # 完整跑（退出删库）
#   KEEP_DB=1 bash scripts/e2e_case_generation.sh    # 保留库便于排查
#   bash scripts/e2e_case_generation.sh -g "并发"     # 透传 playwright 参数
#
# 依赖：backend/.env 里的 DATABASE_URL 提供 PostgreSQL 连接（仅取主机/账号，库名替换为隔离库）。

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
PY="$BACKEND_DIR/.venv/bin/python"
DB_NAME="${E2E_DB_NAME:-testplatform_e2e_gen_$$}"
BACKEND_PORT="${E2E_BACKEND_PORT:-8101}"
FRONTEND_PORT="${E2E_FRONTEND_PORT:-5174}"
STUB_PORT="${E2E_STUB_PORT:-8799}"
KEEP_DB="${KEEP_DB:-0}"

[[ "$DB_NAME" =~ ^testplatform_e2e_[a-zA-Z0-9_]+$ ]] || { echo "ERROR: E2E 库名必须以 testplatform_e2e_ 开头" >&2; exit 2; }

BACKEND_PID=""
FRONTEND_PID=""
STUB_PID=""

# 从 backend/.env 的 DATABASE_URL 派生隔离库连接串（只替换库名，凭据不回显）。
BASE_URL="$(grep -E '^DATABASE_URL=' "$BACKEND_DIR/.env" | tail -1 | cut -d= -f2-)"
[[ -n "$BASE_URL" ]] || { echo "ERROR: backend/.env 缺少 DATABASE_URL" >&2; exit 2; }
DB_URL="$("$PY" - "$BASE_URL" "$DB_NAME" <<'EOF'
import re, sys
url, name = sys.argv[1], sys.argv[2]
# 替换路径段中的库名，保留查询参数（search_path 等）。
print(re.sub(r"(://[^/]+/)[^?]+", rf"\g<1>{name}", url))
EOF
)"

export DATABASE_URL="$DB_URL"
export CORS_ORIGINS="http://127.0.0.1:$FRONTEND_PORT"
export AUTH_COOKIE_SECURE=false
export LANGFUSE_ENABLED=false
export CASE_GENERATION_MAX_ATTEMPTS=1
export AUTH_LOGIN_IP_LIMIT_PER_MINUTE=100000
export AUTH_LOGIN_USERNAME_LIMIT_PER_MINUTE=100000
export SECRET_KEY="$("$PY" -c 'import secrets; print(secrets.token_urlsafe(32))')"
export INIT_ADMIN_USERNAME="${INIT_ADMIN_USERNAME:-e2e-admin}"
export INIT_ADMIN_PASSWORD="${INIT_ADMIN_PASSWORD:-$("$PY" -c 'import secrets; print(secrets.token_urlsafe(18))')}"

# 停止本次启动的测试进程后清理专属隔离库。
cleanup() {
  [[ -n "$FRONTEND_PID" ]] && kill "$FRONTEND_PID" 2>/dev/null
  [[ -n "$BACKEND_PID" ]] && kill "$BACKEND_PID" 2>/dev/null
  [[ -n "$STUB_PID" ]] && kill "$STUB_PID" 2>/dev/null
  wait "$FRONTEND_PID" "$BACKEND_PID" "$STUB_PID" 2>/dev/null || true
  if [[ "$KEEP_DB" != "1" ]]; then
    "$PY" - "$BASE_URL" "$DB_NAME" <<'EOF'
import sys
from urllib.parse import urlparse, urlunparse
import psycopg
base, name = sys.argv[1], sys.argv[2]
parts = urlparse(base.replace("postgresql+psycopg://", "postgresql://", 1))
admin = urlunparse(parts._replace(path="/postgres", query=""))
with psycopg.connect(admin, autocommit=True) as conn:
    conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
    conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
print("[e2e] 隔离库已删除")
EOF
  else
    echo "[e2e] KEEP_DB=1，隔离库 $DB_NAME 已保留"
  fi
}
trap cleanup EXIT

echo "== 1/6 建隔离库并迁移到 head =="
"$PY" - "$BASE_URL" "$DB_NAME" <<'EOF'
import sys
from urllib.parse import urlparse, urlunparse
import psycopg
base, name = sys.argv[1], sys.argv[2]
parts = urlparse(base.replace("postgresql+psycopg://", "postgresql://", 1))
admin = urlunparse(parts._replace(path="/postgres", query=""))
with psycopg.connect(admin, autocommit=True) as conn:
    conn.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
    conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
    conn.execute(f'CREATE DATABASE "{name}"')
print("[e2e] 隔离库已创建")
EOF
(cd "$BACKEND_DIR" && "$PY" -m alembic stamp base >/dev/null && "$PY" -m alembic upgrade head) || { echo "ERROR: 迁移失败" >&2; exit 1; }
"$PY" "$BACKEND_DIR/scripts/seed_admin.py" || { echo "ERROR: 管理员初始化失败" >&2; exit 1; }

# 仅本次隔离库启用两槽位，验收数据库闸门下的模块并行。
"$PY" - "$DB_URL" <<'EOF'
import sys
from sqlalchemy import create_engine, text
with create_engine(sys.argv[1]).begin() as conn:
    conn.execute(text("UPDATE task_scheduler_control SET max_concurrent_runs = 2 WHERE id = 1"))
EOF

echo "== 2/6 起 LLM 桩服务器 :$STUB_PORT =="
"$PY" "$BACKEND_DIR/scripts/llm_stub_server.py" --port "$STUB_PORT" &
STUB_PID=$!
for _ in $(seq 1 30); do curl -sf -o /dev/null "http://127.0.0.1:$STUB_PORT/v1/chat/completions" -X POST -H 'Content-Type: application/json' -d '{}' && break || sleep 0.3; done

echo "== 3/6 起后端 :$BACKEND_PORT =="
(cd "$BACKEND_DIR" && exec "$PY" -m uvicorn app.main:app --port "$BACKEND_PORT" >/tmp/e2e_gen_backend.log 2>&1) &
BACKEND_PID=$!
for _ in $(seq 1 60); do curl -sf -o /dev/null "http://127.0.0.1:$BACKEND_PORT/healthz" && break || sleep 0.5; done
curl -sf -o /dev/null "http://127.0.0.1:$BACKEND_PORT/healthz" || { echo "ERROR: 后端未就绪，见 /tmp/e2e_gen_backend.log" >&2; exit 1; }

echo "== 4/6 通过真实 API 种入指向桩的默认模型配置 =="
TOKEN="$(curl -sf -X POST "http://127.0.0.1:$BACKEND_PORT/api/v1/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$INIT_ADMIN_USERNAME\",\"password\":\"$INIT_ADMIN_PASSWORD\"}" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')" \
  || { echo "ERROR: 管理员登录失败" >&2; exit 1; }
curl -sf -X POST "http://127.0.0.1:$BACKEND_PORT/api/v1/model-configs" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"label\":\"E2E 桩模型\",\"provider\":\"openai-compatible\",\"api_base\":\"http://127.0.0.1:$STUB_PORT/v1\",\"model_name\":\"e2e-stub-model\",\"api_key\":\"e2e-dummy-key\",\"is_enabled\":true,\"is_default\":true}" \
  >/dev/null || { echo "ERROR: 模型配置创建失败" >&2; exit 1; }

echo "== 5/6 起前端 Vite :$FRONTEND_PORT =="
(cd "$FRONTEND_DIR" && VITE_API_PROXY_TARGET="http://127.0.0.1:$BACKEND_PORT" exec npx vite --port "$FRONTEND_PORT" --strictPort >/tmp/e2e_gen_frontend.log 2>&1) &
FRONTEND_PID=$!
for _ in $(seq 1 60); do curl -sf -o /dev/null "http://127.0.0.1:$FRONTEND_PORT" && break || sleep 0.5; done
curl -sf -o /dev/null "http://127.0.0.1:$FRONTEND_PORT" || { echo "ERROR: 前端未就绪，见 /tmp/e2e_gen_frontend.log" >&2; exit 1; }

echo "== 6/6 Playwright 验收 =="
set +e
(cd "$FRONTEND_DIR" && \
  E2E_BASE_URL="http://127.0.0.1:$FRONTEND_PORT" \
  E2E_API_URL="http://127.0.0.1:$BACKEND_PORT/api/v1" \
  E2E_ADMIN_USERNAME="$INIT_ADMIN_USERNAME" \
  E2E_ADMIN_PASSWORD="$INIT_ADMIN_PASSWORD" \
  npx playwright test "$@")
RESULT=$?
echo "== E2E 结果：$([ $RESULT -eq 0 ] && echo 通过 || echo 失败) =="
exit $RESULT
