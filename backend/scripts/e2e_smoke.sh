#!/usr/bin/env bash
# 第一阶段端到端冒烟验证。
#
# 在**隔离数据库**上从零开始：建库 → Alembic 迁移 → 管理员初始化（再跑一次验证幂等）
# → 启动后端 → 用真实 HTTP 请求走通关键流程 → 退出时清理。
# 不读取、不复制、不依赖旧项目数据库，也不改动开发库 testplatform_dev。
#
# 用法（凭据一律显式提供；脚本不内置任何默认账号密码）：
#   INIT_ADMIN_USERNAME=e2e-admin \
#   INIT_ADMIN_PASSWORD='E2E-Password-456' \
#   bash scripts/e2e_smoke.sh \
#     --database-url 'postgresql+psycopg://root:pwd@127.0.0.1:5432/testplatform_e2e'
#
# 可选：--port 8001   --keep-db   --frontend-url http://localhost:5173
#
# 输出只打印判定结果；凭据与数据库连接串一律掩码。

set -uo pipefail

# ---- 全局变量 ----
# BACKEND_DIR  仓库后端目录（脚本所在目录的上一级），用于定位 venv 与种子脚本
# PY           后端 venv 里的解释器；不依赖 PATH 上的 python
# HOST/PORT    临时后端的监听地址；PORT 会被 --port 覆盖
# KEEP_DB      1 时退出前保留测试数据库（便于事后排查），0 时删除
# FRONTEND_URL 传了才校验 Vite 代理；不传则跳过第 13 组
# DB_URL       被测隔离库连接串，允许含驱动前缀（postgresql+psycopg://）
# SERVER_PID   临时后端进程号，cleanup 用它回收进程
# BODY_FILE    最近一次响应的落盘位置，供断言读取响应字段
BACKEND_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$BACKEND_DIR/.venv/bin/python"
HOST="127.0.0.1"
PORT="8001"
KEEP_DB=0
FRONTEND_URL=""
DB_URL="${DATABASE_URL:-}"
SERVER_PID=""
BODY_FILE="/tmp/_e2e_body.json"

# 命令行参数解析；缺省值见上面的全局变量
while [[ $# -gt 0 ]]; do
  case "$1" in
    --database-url)   DB_URL="$2"; shift 2 ;;
    --port)           PORT="$2"; shift 2 ;;
    --keep-db)        KEEP_DB=1; shift ;;
    --frontend-url)   FRONTEND_URL="$2"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

# 未显式给出 DATABASE_URL 时从 backend/.env 读取（.env 已在 .gitignore 中）。
if [[ -z "$DB_URL" && -f "$BACKEND_DIR/.env" ]]; then
  DB_URL="$(grep -E '^DATABASE_URL=' "$BACKEND_DIR/.env" | tail -1 | cut -d= -f2-)"
fi
[[ -n "$DB_URL" ]] || { echo "ERROR: DATABASE_URL 未配置，请用 --database-url 指定隔离数据库" >&2; exit 2; }
: "${INIT_ADMIN_USERNAME:?必须显式设置 INIT_ADMIN_USERNAME}"
: "${INIT_ADMIN_PASSWORD:?必须显式设置 INIT_ADMIN_PASSWORD}"

REDACT="${INIT_ADMIN_PASSWORD}|${DB_URL}|${DATABASE_URL:-}"
REDACT="${REDACT%|}"
# 掩码规则：把管理员密码、被测库连接串与 .env 里的连接串替换成 <redacted>。
# 用 LC_ALL=C 让 sed 在多字节环境下也按字节匹配，避免 UTF-8 截断出错。
redact() { LC_ALL=C sed -E "s#${REDACT}#<redacted>#g"; }

# 断言计数：PASS/FAIL 只在下面的断言函数里增减，最后据 FAIL 决定退出码
PASS=0
FAIL=0
# check <名称> <实际值> <预期值>  严格字符串相等判定
check() { # check <名称> <实际> <预期>
  if [[ "$2" == "$3" ]]; then
    PASS=$((PASS + 1)); printf '  ok   %-46s (%s)\n' "$1" "$2"
  else
    FAIL=$((FAIL + 1)); printf '  FAIL %-46s 实际=%s 预期=%s\n' "$1" "$2" "$3"
  fi
}
# ok_note / note：没有确定预期值时用的成功与失败断言（只能做存在性判断的场景）
ok_note() { printf '  ok   %s\n' "$1"; PASS=$((PASS + 1)); }
note() { printf '  FAIL %-46s %s\n' "$1" "$2"; FAIL=$((FAIL + 1)); }
# status_of：只取 HTTP 状态码，响应体落在 $BODY_FILE 便于断言响应字段
status_of() { curl -s -o "$BODY_FILE" -w '%{http_code}' "$@"; }
# post_json <url> <json> [bearer_token]  带令牌则加 Authorization 头，否则按匿名请求发
post_json() { # post_json <url> <json> [bearer_token]
  local url="$1" payload="$2" tk="${3:-}"
  if [[ -n "$tk" ]]; then
    curl -s -o "$BODY_FILE" -w '%{http_code}' -X POST "$url" \
      -H 'Content-Type: application/json' -H "Authorization: Bearer $tk" -d "$payload"
  else
    curl -s -o "$BODY_FILE" -w '%{http_code}' -X POST "$url" \
      -H 'Content-Type: application/json' -d "$payload"
  fi
}
# body：对 $BODY_FILE 执行 jq 过滤表达式并去掉换行
body() { jq -c "$@" "$BODY_FILE"; }
# 统一在这里拼 JSON，避免在命令替换里写转义引号（bash 会把它拆成多个词）
json_pair() { printf '{"%s":"%s","%s":"%s"}' "$1" "$2" "$3" "$4"; }

cleanup() {
  if [[ -n "$SERVER_PID" ]]; then
    kill "$SERVER_PID" 2>/dev/null
    # wait 既确保服务真正退出（否则 DROP DATABASE 会被连接占住），
    # 又消费掉作业状态，避免 bash 打印 Terminated: 15 之类的噪音。
    wait "$SERVER_PID" 2>/dev/null
  fi
  if [[ "$KEEP_DB" == 0 ]]; then
    echo
    echo "== 清理测试数据库 =="
    # 连接串通过环境变量传，不用 argv：shell 前缀赋值 VAR=x cmd "$VAR" 会先展开
    # 再赋值的 $VAR（外层看不到），空串会让脚本在读参处就崩掉。
    E2E_DATABASE_URL="$DB_URL" "$PY" - <<'PYCLEAN' | redact
"""删除本次冒烟用的隔离测试库。

连接串从环境变量 E2E_DATABASE_URL 取（不走 argv，原因见上方的 shell 注释）。
删除前先终止库上的其他连接，否则 DROP DATABASE 会因为活动连接而失败。
任何失败都必须打印出来，不能静默——留一个库比假装清理干净危险得多。
"""
import os, psycopg

url = (os.environ.get("E2E_DATABASE_URL") or "").strip()
if not url or "@" not in url:
    print("清理失败：没有拿到数据库连接串")
    raise SystemExit(0)
# 去掉驱动前缀（postgresql+psycopg -> postgresql），psycopg 直接连不需要它
scheme, rest = url.split("://", 1)
scheme = scheme.split("+", 1)[0]
# 保留完整的 user:password：只取密码会拼成 postgresql://pwd@host/db，
# psycopg 把密码当成用户名，报 fe_sendauth: no password supplied。
auth_part, target = rest.split("@", 1)
host = target.split("/", 1)[0]
db = target.rsplit("/", 1)[-1]
try:
    # 连库管理目录（postgres），才能对别的库执行 DROP
    conn = psycopg.connect(f"{scheme}://{auth_part}@{host}/postgres", autocommit=True)
    if not conn.execute(
        "SELECT 1 FROM pg_database WHERE datname=%s", (db,)
    ).fetchone():
        print(f"测试数据库已不存在：{db}")
    else:
        conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname=%s AND pid <> pg_backend_pid()", (db,)
        )
        conn.execute(f'DROP DATABASE "{db}"')
        print(f"已清理测试数据库：{db}")
except Exception as exc:  # 清理失败必须看得见，不能静默
    print(f"清理失败（请手动删除 {db}）：{type(exc).__name__}: {exc}")
PYCLEAN
  fi
}
trap cleanup EXIT

echo "== 1. 初始化隔离数据库（建库 + Alembic 迁移 + 种子）=="
INIT_ADMIN_USERNAME="$INIT_ADMIN_USERNAME" INIT_ADMIN_PASSWORD="$INIT_ADMIN_PASSWORD" \
  "$PY" "$BACKEND_DIR/scripts/seed_admin.py" --database-url "$DB_URL" --drop 2>&1 | redact | tail -6
check "初始化脚本退出码" "${PIPESTATUS[0]}" "0"

echo "== 2. 幂等：重复初始化不报错、不重复插入 =="
INIT_ADMIN_USERNAME="$INIT_ADMIN_USERNAME" INIT_ADMIN_PASSWORD="$INIT_ADMIN_PASSWORD" \
  "$PY" "$BACKEND_DIR/scripts/seed_admin.py" --database-url "$DB_URL" 2>&1 | redact > /tmp/_e2e_seed2.log
check "重复初始化退出码" "${PIPESTATUS[0]}" "0"
grep -q '管理员已存在' /tmp/_e2e_seed2.log && ok_note "管理员已存在时跳过，不覆盖历史密码" \
  || note "重复初始化未跳过管理员" ""
grep -q '新增 0 条' /tmp/_e2e_seed2.log && ok_note "内置环境不重复插入" \
  || note "内置环境重复插入" ""

echo "== 3. 启动后端 =="
DATABASE_URL="$DB_URL" AUTO_CREATE_SCHEMA=false \
  INIT_ADMIN_USERNAME="$INIT_ADMIN_USERNAME" INIT_ADMIN_PASSWORD="$INIT_ADMIN_PASSWORD" \
  "$PY" -m uvicorn app.main:app --app-dir "$BACKEND_DIR" \
    --host "$HOST" --port "$PORT" --log-level warning > /tmp/_e2e_server.log 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 60); do
  curl -sf "http://$HOST:$PORT/healthz" >/dev/null 2>&1 && break
  sleep 0.5
done
check "健康检查" "$(curl -s "http://$HOST:$PORT/healthz" | jq -r .status)" "ok"
echo "       后端地址：http://$HOST:$PORT"

BASE="http://$HOST:$PORT"
API="$BASE/api/v1"

echo "== 4. 注册 / 登录 / me =="
U1="e2e-user-${RANDOM}"; U2="e2e-user2-${RANDOM}"
P1='E2E-Pass-123'; P2='E2E-Pass-456'
J1="$(json_pair username "$U1" password "$P1")"
check "注册 201" "$(post_json "$API/register" "$J1")" "201"
JLOGIN1="$(json_pair username "$U1" password "$P1")"
check "登录 200" "$(post_json "$API/login" "$JLOGIN1")" "200"
T1="$(body -r .access_token)"
[[ "$T1" =~ ey ]] && ok_note "登录返回 JWT" || note "登录响应异常" "$(body .)"
jq -e '.expires_in > 0 and .token_type == "bearer" and .user' "$BODY_FILE" >/dev/null \
  && ok_note "响应含 expires_in / token_type / user" || note "登录响应字段缺失" "$(body .)"
check "注册即创建个人组织" "$(curl -s "$API/me/organizations" -H "Authorization: Bearer $T1" | jq -r .total)" "1"
check "重复注册 409" "$(post_json "$API/register" "$J1")" "409"
check "me 200" "$(status_of "$API/me" -H "Authorization: Bearer $T1")" "200"
check "me 用户名一致" "$(body -r .username)" "$U1"
JWP="$(json_pair username "$U1" password wrong-pass)"
check "错误密码 400" "$(post_json "$API/login" "$JWP")" "400"
JNX="$(json_pair username no-such-user-xx password whatever-1)"
check "不存在的用户名 400" "$(post_json "$API/login" "$JNX")" "400"
check "两种失败文案一致" "$(body -r .message)" "用户名或密码错误"
check "无令牌 401" "$(status_of "$API/me")" "401"
check "401 统一文案" "$(body -r .message)" "登录失效，请重新登录"
check "401 统一错误码" "$(body -r .code)" "ERR_TOKEN_EXPIRED"
check "非 Bearer 头同样 401" "$(status_of "$API/me" -H 'Authorization: Basic abcdef')" "401"
check "401 携带 WWW-Authenticate" \
  "$(curl -s -D - -o /dev/null "$API/me" | grep -ci '^WWW-Authenticate: Bearer')" "1"
check "退出登录 204（服务端不维护会话）" "$(status_of -X POST "$API/logout" -H "Authorization: Bearer $T1")" "204"

echo "== 5. 非管理员不得调用平台管理端 =="
for path in "$API/users" "$API/environments" "$API/model-configs" "$API/dashboard/platform"; do
  check "普通用户 GET ${path#$BASE} 403" "$(status_of "$path" -H "Authorization: Bearer $T1")" "403"
done

echo "== 6. 管理员端 =="
JADM="$(json_pair username "$INIT_ADMIN_USERNAME" password "$INIT_ADMIN_PASSWORD")"
check "管理员登录 200" "$(post_json "$API/login" "$JADM")" "200"
ADM="$(body -r .access_token)"
[[ -n "$ADM" && "$ADM" != "null" ]] || { note "管理员令牌为空" "$(body .)"; exit 1; }
check "管理员 /users 200" "$(status_of "$API/users?page=1&page_size=5" -H "Authorization: Bearer $ADM")" "200"
body -e '.page and .page_size and .total and .items' >/dev/null \
  && ok_note "分页字段 page/page_size/total/items 齐全" || note "分页字段缺失" "$(body .)"
check "page_size 超上限 422" "$(status_of "$API/users?page_size=201" -H "Authorization: Bearer $ADM")" "422"
check "page<1 422" "$(status_of "$API/users?page=0" -H "Authorization: Bearer $ADM")" "422"
check "关键字搜索 200" "$(status_of "$API/users?keyword=$U1&page_size=10" -H "Authorization: Bearer $ADM")" "200"
check "搜索命中 1 条" "$(body -r '.items | length')" "1"
check "管理员 /environments 200" "$(status_of "$API/environments" -H "Authorization: Bearer $ADM")" "200"
ENV_ROWS="$(body -r '.items | length')"
[[ "$ENV_ROWS" -ge 4 ]] && ok_note "内置环境就位（$ENV_ROWS 条）" \
  || note "内置环境缺失（$ENV_ROWS 条）" ""
check "管理员 /dashboard/platform 200" "$(status_of "$API/dashboard/platform" -H "Authorization: Bearer $ADM")" "200"
check "平台口径标记" "$(body -r .scope.is_platform_admin)" "true"

echo "== 7. 组织 / 项目 / 跨组织隔离 =="
J2="$(json_pair username "$U2" password "$P2")"
check "第二个用户注册 201" "$(post_json "$API/register" "$J2")" "201"
JLOGIN2="$(json_pair username "$U2" password "$P2")"
check "登录第二个用户 200" "$(post_json "$API/login" "$JLOGIN2")" "200"
T2="$(body -r .access_token)"
JORG='{"name":"E2E 隔离组甲"}'
check "u1 建组织 201" "$(status_of -X POST "$API/organizations" -H "Authorization: Bearer $T1" \
  -H 'Content-Type: application/json' -d "$JORG")" "201"
ORG1="$(body -r .id)"
U2_ID="$(curl -s "$API/me" -H "Authorization: Bearer $T2" | jq -r .id)"
JMEM="$(printf '{"user_id":%s,"role":"member"}' "$U2_ID")"
check "加入组织（幂等 upsert 200）" "$(status_of -X PUT "$API/organizations/$ORG1/members/$U2_ID" \
  -H "Authorization: Bearer $T1" -H 'Content-Type: application/json' -d "$JMEM")" "200"
check "成员角色生效" "$(body -r .role)" "member"
check "重复加入仍是 200" "$(status_of -X PUT "$API/organizations/$ORG1/members/$U2_ID" \
  -H "Authorization: Bearer $T1" -H 'Content-Type: application/json' -d "$JMEM")" "200"
JPROJ1="$(printf '{"name":"E2E 项目甲","organization_id":%s}' "$ORG1")"
check "u1 建组织内项目 201" "$(status_of -X POST "$API/projects" -H "Authorization: Bearer $T1" \
  -H 'Content-Type: application/json' -d "$JPROJ1")" "201"
PROJ1="$(body -r .id)"
JPROJ2='{"name":"E2E 项目乙"}'
check "u2 建个人项目 201" "$(status_of -X POST "$API/projects" -H "Authorization: Bearer $T2" \
  -H 'Content-Type: application/json' -d "$JPROJ2")" "201"
PROJ2="$(body -r .id)"
check "u1 可见项目 1 条" "$(curl -s "$API/projects" -H "Authorization: Bearer $T1" | jq -r .total)" "1"
check "u2 可见项目 1 条（组织普通成员只看到自己被分配的项目）" \
  "$(curl -s "$API/projects" -H "Authorization: Bearer $T2" | jq -r .total)" "1"
check "项目详情可见 200" "$(status_of "$API/projects/$PROJ1" -H "Authorization: Bearer $T1")" "200"
check "跨组织项目详情 404" "$(status_of "$API/projects/$PROJ1" -H "Authorization: Bearer $T2")" "404"
check "404 错误码" "$(body -r .code)" "ERR_NOT_FOUND"
check "跨组织项目不在他人列表" \
  "$(curl -s "$API/projects" -H "Authorization: Bearer $T2" \
     | jq -r --argjson id "$PROJ1" '[.items[] | select(.id == $id)] | length')" "0"
check "跨组织成员表 404" "$(status_of "$API/projects/$PROJ1/members" -H "Authorization: Bearer $T2")" "404"
check "跨组织出站目标 404" "$(status_of "$API/projects/$PROJ1/targets" -H "Authorization: Bearer $T2")" "404"
check "不存在的资源 404" "$(status_of "$API/projects/99999999" -H "Authorization: Bearer $T1")" "404"

echo "== 8. 只读成员不可写 =="
JVIEW="$(printf '{"user_id":%s,"role":"viewer"}' "$U2_ID")"
check "加为 viewer（upsert 200）" "$(status_of -X PUT "$API/projects/$PROJ1/members/$U2_ID" \
  -H "Authorization: Bearer $T1" -H 'Content-Type: application/json' -d "$JVIEW")" "200"
check "viewer 读项目 200" "$(status_of "$API/projects/$PROJ1" -H "Authorization: Bearer $T2")" "200"
check "viewer 看到自己的角色" "$(body -r .my_role)" "viewer"
check "viewer 读成员表 200" "$(status_of "$API/projects/$PROJ1/members" -H "Authorization: Bearer $T2")" "200"
check "授权后 u2 可见项目变 2 条" \
  "$(curl -s "$API/projects" -H "Authorization: Bearer $T2" | jq -r .total)" "2"
check "viewer 改项目 403" "$(status_of -X PATCH "$API/projects/$PROJ1" \
  -H "Authorization: Bearer $T2" -H 'Content-Type: application/json' -d '{"description":"越权写入"}')" "403"
JEDIT="$(printf '{"user_id":%s,"role":"editor"}' "$U2_ID")"
check "viewer 改成员 403" "$(status_of -X PUT "$API/projects/$PROJ1/members/$U2_ID" \
  -H "Authorization: Bearer $T2" -H 'Content-Type: application/json' -d "$JEDIT")" "403"
check "viewer 删项目 403" "$(status_of -X DELETE "$API/projects/$PROJ1" -H "Authorization: Bearer $T2")" "403"
JOWN="$(printf '{"user_id":%s}' "$U2_ID")"
check "viewer 转负责人 403" "$(status_of -X POST "$API/projects/$PROJ1/owner" \
  -H "Authorization: Bearer $T2" -H 'Content-Type: application/json' -d "$JOWN")" "403"
check "viewer 403 错误码" "$(body -r .code)" "ERR_FORBIDDEN"

echo "== 9. 令牌撤销 / 角色变更 / 禁用 =="
OLD="$T2"
JCP='{"old_password":"E2E-Pass-456","new_password":"E2E-Pass-789"}'
check "修改自己的密码 200" "$(status_of -X PATCH "$API/me" \
  -H "Authorization: Bearer $OLD" -H 'Content-Type: application/json' -d "$JCP")" "200"
check "改密码后旧令牌 401" "$(status_of "$API/me" -H "Authorization: Bearer $OLD")" "401"
check "改密码后文案统一" "$(body -r .message)" "登录失效，请重新登录"
JNEW="$(json_pair username "$U2" password E2E-Pass-789)"
check "新密码可登录" "$(post_json "$API/login" "$JNEW")" "200"
NEW="$(body -r .access_token)"
check "管理员变更平台角色 200" "$(status_of -X PATCH "$API/users/$U2_ID" \
  -H "Authorization: Bearer $ADM" -H 'Content-Type: application/json' -d '{"role":"dev"}')" "200"
check "角色变更后旧令牌 401" "$(status_of "$API/me" -H "Authorization: Bearer $NEW")" "401"
check "管理员停用账号 200" "$(status_of -X PATCH "$API/users/$U2_ID" \
  -H "Authorization: Bearer $ADM" -H 'Content-Type: application/json' -d '{"is_active":false}')" "200"
check "停用账号登录被拒 403" "$(post_json "$API/login" "$JNEW")" "403"
check "停用文案" "$(body -r .message)" "该账户已被禁用"
check "管理员不能停用自己的账户" "$(status_of -X PATCH "$API/users/1" \
  -H "Authorization: Bearer $ADM" -H 'Content-Type: application/json' -d '{"is_active":false}')" "400"
check "自停用文案" "$(body -r .message)" "不能停用自己的账户"
JSA='{"username":"e2e-second-admin","password":"E2E-Password-123","role":"admin"}'
check "创建第二个管理员 201" "$(post_json "$API/users" "$JSA" "$ADM")" "201"
SEC_ID="$(body -r .id)"
check "管理员不能停用其他管理员" "$(status_of -X PATCH "$API/users/$SEC_ID" \
  -H "Authorization: Bearer $ADM" -H 'Content-Type: application/json' -d '{"is_active":false}')" "400"
check "停用管理员的文案" "$(body -r .message)" "不能停用管理员账户"
check "管理员不能删除自己" "$(status_of -X DELETE "$API/users/1" -H "Authorization: Bearer $ADM")" "403"
check "管理员不能删除其他管理员" "$(status_of -X DELETE "$API/users/$SEC_ID" -H "Authorization: Bearer $ADM")" "400"

echo "== 10. 看板 / 就绪 / 未接入标记 =="
check "看板 200" "$(status_of "$API/dashboard/overview" -H "Authorization: Bearer $ADM")" "200"
body -e '.scope and .stats' >/dev/null && ok_note "看板返回 scope 与 stats" \
  || note "看板缺少 scope/stats" "$(body .)"
for key in test_runs reports defects; do
  # jq 过滤表达式先放进变量再传，避免在命令替换里写转义引号
  FILT_HINT="$(printf '.stats[] | select(.key=="%s") | .hint' "$key")"
  FILT_VALUE="$(printf '.stats[] | select(.key=="%s") | .value' "$key")"
  check "$key 标记未接入" "$(body -r "$FILT_HINT")" "未接入"
  check "$key 不伪造统计值" "$(body -r "$FILT_VALUE")" "0"
done
check "已接入项不标记未接入" \
  "$(body -r '.stats[] | select(.key=="projects") | .hint')" "当前用户可见范围（平台管理员：全部）"
check "就绪检查 200" "$(status_of "$API/dashboard/ready" -H "Authorization: Bearer $ADM")" "200"
check "数据库就绪 up" "$(body -r '.checks[] | select(.name=="database") | .status')" "up"
check "未配模型时不谎报 ready" \
  "$(jq -r 'if .status == "ready" then "ready" else "not-ready" end' "$BODY_FILE")" "not-ready"

echo "== 11. 模型密钥不泄露 / 启用必须有密钥 =="
JNODE='{"domain_id":"e2e-domain","label":"E2E 模型","api_base":"https://api.example.com/v1","model_name":"gpt-4o","is_enabled":true}'
check "启用但无密钥 400" "$(status_of -X POST "$API/model-configs" -H "Authorization: Bearer $ADM" \
  -H 'Content-Type: application/json' -d "$JNODE")" "400"
JOFF='{"domain_id":"e2e-domain-off","label":"E2E 停用模型","api_base":"https://api.example.com/v1","model_name":"gpt-4o","is_enabled":false}'
check "停用且无密钥允许" "$(status_of -X POST "$API/model-configs" -H "Authorization: Bearer $ADM" \
  -H 'Content-Type: application/json' -d "$JOFF")" "201"
OFF_ID="$(body -r .id)"
JK='{"domain_id":"e2e-domain","label":"E2E 模型","api_base":"https://api.example.com/v1","model_name":"gpt-4o","api_key":"sk-e2e-live-only-987654","is_enabled":true}'
CREATED_CODE="$(curl -s -o /tmp/_e2e_created.json -w '%{http_code}' -X POST "$API/model-configs" \
  -H "Authorization: Bearer $ADM" -H 'Content-Type: application/json' -d "$JK")"
check "配置创建 201" "$CREATED_CODE" "201"
MID="$(jq -r .id /tmp/_e2e_created.json)"
check "响应不含 api_key 字段" "$(jq -r 'has("api_key")' /tmp/_e2e_created.json)" "false"
check "响应含 has_api_key=true" "$(jq -r .has_api_key /tmp/_e2e_created.json)" "true"
MASKED="$(jq -r .masked_api_key /tmp/_e2e_created.json)"
# 注意：字符串里的 $VAR 后面不能紧跟全角/多字节字符（bash 3.2 在 C.UTF-8 下
# 会把那个字符并入变量名，触发 unbound variable）。一律加花括号或改用 ASCII 分隔。
if [[ -n "$MASKED" ]] && ! printf '%s' "$MASKED" | grep -q 'sk-e2e-live-only'; then
  ok_note "只回掩码，不回明文密钥"
else
  note "掩码异常（疑似泄露明文）" "$MASKED"
fi
check "列表接口不含明文密钥" "$(curl -s "$API/model-configs" -H "Authorization: Bearer $ADM" | grep -c 'sk-e2e-live-only')" "0"
check "编辑留空保留原密钥" "$(curl -s -X PATCH "$API/model-configs/$MID" \
  -H "Authorization: Bearer $ADM" -H 'Content-Type: application/json' \
  -d '{"label":"E2E 模型已改名"}' | jq -r .has_api_key)" "true"
check "停用模型可删除" "$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$API/model-configs/$OFF_ID" \
  -H "Authorization: Bearer $ADM")" "204"

echo "== 12. 数据真实落库（不是内存态）=="
# 期望行数由上面的步骤推导：
#   user                4 = 种子管理员 + 第二个管理员 + 注册的两个普通用户
#   organization        5 = 四个人的个人组织 + 手动建的「E2E 隔离组甲」
#                        （注册与「管理员新建用户」都会自动建个人组织）
#   organization_member 6 = 四个个人组织负责人 + 隔离组甲的负责人与成员
#   project             2 = 隔离组甲内项目 + 第二个用户的个人项目
#   project_member      1 = 唯一一条显式成员授权（viewer）；建项目不写成员行，
#                           负责人经 project.owner_id 生效
#   model_configuration 1 = 启用配置保留，停用配置已删除
#   environment         4 = 种子内置环境
DB_ROWS="$("$PY" - "$DB_URL" <<'PYDB'
"""直接查库统计各表行数，用来验证写入真的持久化了、而不是内存态。

连接串允许带 postgresql+psycopg 驱动前缀，psycopg 不接受，这里先剥掉。
统计口径：public schema 下除 alembic_version 外的所有表；同时返回表数量，
用来确认迁移把约定数量的表都建出来了。
"""
import json, sys, psycopg
conn = psycopg.connect(sys.argv[1].replace("postgresql+psycopg", "postgresql"), autocommit=True)
def count(table):
    return conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
tables = [r[0] for r in conn.execute(
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public'")]
rows = {t: count(t) for t in tables if t != "alembic_version"}
conn.close()
print(json.dumps({"tables": len(tables), **rows}, ensure_ascii=False, sort_keys=True))
PYDB
)"
echo "       数据库内容：$DB_ROWS"
check "建表数 10（含 alembic_version）" "$(printf '%s' "$DB_ROWS" | jq -r .tables)" "10"
check "user 落库 4 行" "$(printf '%s' "$DB_ROWS" | jq -r .user)" "4"
check "organization 落库 5 行" "$(printf '%s' "$DB_ROWS" | jq -r .organization)" "5"
check "organization_member 落库 6 行" "$(printf '%s' "$DB_ROWS" | jq -r .organization_member)" "6"
check "project 落库 2 行" "$(printf '%s' "$DB_ROWS" | jq -r .project)" "2"
check "project_member 落库 1 行" "$(printf '%s' "$DB_ROWS" | jq -r .project_member)" "1"
check "model_configuration 落库 1 行" "$(printf '%s' "$DB_ROWS" | jq -r .model_configuration)" "1"
check "environment 落库 4 行" "$(printf '%s' "$DB_ROWS" | jq -r .environment)" "4"
check "通知表存在（未接入的业务表也要建）" "$(printf '%s' "$DB_ROWS" | jq -r 'has("notification")')" "true"

echo "== 13. 前端与代理（需先 npm run dev）=="
if [[ -n "$FRONTEND_URL" ]]; then
  check "首页 200" "$(curl -s -o /dev/null -w '%{http_code}' "$FRONTEND_URL/")" "200"
  check "SPA 回退 /admin/users" "$(curl -s -o /dev/null -w '%{http_code}' "$FRONTEND_URL/admin/users")" "200"
  check "SPA 回退 /console" "$(curl -s -o /dev/null -w '%{http_code}' "$FRONTEND_URL/console")" "200"
  # 代理必须把 /api/v1 原样转发（旧前端会剥掉 /api 前缀，本项目故意不剥）。
  # 判据：经代理与直连后端对同一端点的响应码一致；若前缀被剥离，后端看到的是
  # /v1/me 而不是 /api/v1/me，会是 404 而非 401。
  DIRECT_CODE="$(curl -s -o /tmp/_e2e_direct.json -w '%{http_code}' "$BASE/api/v1/me")"
  VIA_CODE="$(curl -s -o /tmp/_e2e_via.json -w '%{http_code}' "$FRONTEND_URL/api/v1/me")"
  check "经代理与直连同码（前缀未被剥离）" "${DIRECT_CODE}/${VIA_CODE}" "401/401"
  check "401 经代理仍为统一文案" "$(jq -r .message /tmp/_e2e_via.json)" "登录失效，请重新登录"
  check "代理不剥离前缀：/api/healthz 不存在" \
    "$(curl -s -o /dev/null -w '%{http_code}' "$FRONTEND_URL/api/healthz")" "404"
  check "首页含 React 挂载点" "$(curl -s "$FRONTEND_URL/" | grep -c 'id="root"')" "1"
  check "入口模块可访问（Vite dev 模式）" "$(curl -s -o /dev/null -w '%{http_code}' "$FRONTEND_URL/src/main.tsx")" "200"
else
  echo "  skip  未提供 --frontend-url，跳过 Vite 代理校验"
fi

echo
printf '== 结果：%d 通过，%d 失败 ==\n' "$PASS" "$FAIL"
[[ "$FAIL" == 0 ]]
