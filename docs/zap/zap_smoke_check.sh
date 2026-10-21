#!/usr/bin/env bash
# =============================================================================
# OWASP ZAP 部署冒烟检查（Security Testing Phase 2）
#
# 用途：在**真实** ZAP 实例上确认平台连接器依赖的 REST API 可用，
#       并在提交扫描任务之前发现契约不匹配。
#
# ⚠️ 状态说明（务必阅读）：
#   本脚本由 Phase 2 开发阶段编写，但**从未在任何真实 ZAP 实例上执行过**——
#   开发环境没有 Docker daemon，全部单测都跑在自带的 Mock 连接器
#   （app/features/security_testing/zap/mock.py）上。因此：
#     1. 脚本里每一项都必须由部署方实际跑一遍；
#     2. 任何 FAIL 都先怀疑「平台与真实 ZAP 的契约不匹配」，不要直接改脚本；
#     3. 结果要回填到《Security Testing Phase 2 OWASP ZAP 集成交付报告》
#        的「真实 ZAP 验证」一节，不能替部署方勾选。
#
# 用法：
#   export ZAP_BASE_URL="http://127.0.0.1:8090"
#   export ZAP_API_KEY="可选；ZAP_API_KEY_MODE=header 时走 X-ZAP-API-Key"
#   ./docs/zap/zap_smoke_check.sh            # 只读探针（默认）
#   WITH_WRITES=1 ./docs/zap/zap_smoke_check.sh   # 额外执行配置写入探针
#
# 退出码：0 = 无 FAIL；1 = 有 FAIL；2 = 环境不满足（缺 curl / 未设地址）。
#
# 重要口径：**HTTP 200 不等于成功**。ZAP 对未知方法、缺参数也经常返回 200
# 并带上 {"error": "..."}。所以每项分三态：
#   OK      = 200 且响应里没有 error 键（契约可用）
#   PARAMS  = 200 但响应含 error 键（端点存在，参数或前置条件不满足）
#   ERROR   = 非 200 / 连接失败（端点缺失、地址不对、需要 API Key）
# =============================================================================
set -uo pipefail

BASE_URL="${ZAP_BASE_URL:-}"
API_KEY="${ZAP_API_KEY:-}"
KEY_MODE="${ZAP_API_KEY_MODE:-header}"
MIN_VERSION="2.12.0"
WITH_WRITES="${WITH_WRITES:-0}"

OK=0
PARAMS=0
ERR=0

ok()   { printf '  OK     %s\n' "$1"; OK=$((OK + 1)); }
param(){ printf '  PARAMS %s\n' "$1"; PARAMS=$((PARAMS + 1)); }
err()  { printf '  ERROR  %s\n' "$1"; ERR=$((ERR + 1)); }

TMP_BODY="$(mktemp "${TMPDIR:-/tmp}/zap_smoke_body.XXXXXX")"
TMP_ERR="${TMP_BODY}.err"
cleanup() { rm -f "$TMP_BODY" "$TMP_ERR"; }
trap cleanup EXIT

if ! command -v curl >/dev/null 2>&1; then
  echo "缺少 curl，无法执行" >&2
  exit 2
fi
if [ -z "$BASE_URL" ]; then
  echo "未设置 ZAP_BASE_URL（例：export ZAP_BASE_URL=http://127.0.0.1:8090）" >&2
  exit 2
fi

echo "目标：${BASE_URL}"
echo "最低版本要求：${MIN_VERSION}"
echo

AUTH_ARGS=()
if [ -n "$API_KEY" ]; then
  if [ "$KEY_MODE" = "query" ]; then
    AUTH_ARGS=(-H "Accept: application/json" --data-urlencode "apikey=${API_KEY}")
  else
    AUTH_ARGS=(-H "Accept: application/json" -H "X-ZAP-API-Key: ${API_KEY}")
  fi
else
  AUTH_ARGS=(-H "Accept: application/json")
fi

# 调一次 ZAP API。
# 返回码：0 = OK（200 且无 error 键）；1 = PARAMS（200 但含 error 键）；2 = ERROR。
# 响应体始终写到 stdout，便于人眼看错误原因。
zap_call() {
  local method="$1" path="$2"
  local code
  if [ "$method" = "GET" ]; then
    code=$(curl -sS -m 20 -o "$TMP_BODY" -w '%{http_code}' \
      "${AUTH_ARGS[@]}" "${BASE_URL}${path}?format=json" 2>"$TMP_ERR")
  else
    code=$(curl -sS -m 20 -X POST -o "$TMP_BODY" -w '%{http_code}' \
      "${AUTH_ARGS[@]}" "${BASE_URL}${path}?format=json" 2>"$TMP_ERR")
  fi
  local curl_err=""
  if [ -s "$TMP_ERR" ]; then
    curl_err=" curl: $(head -1 "$TMP_ERR")"
  fi
  cat "$TMP_BODY" 2>/dev/null
  echo

  if [ "$code" != "200" ]; then
    echo "     → HTTP ${code}${curl_err}"
    return 2
  fi
  if grep -q '"error"' "$TMP_BODY"; then
    echo "     → 200 但响应带 error 键（端点存在，参数/前置条件不满足）"
    return 1
  fi
  return 0
}

# 跑一次探针并按三态打印。$3 是 PARAMS 时的补充说明。
# 非 OK 时把响应体摘一小段出来，方便人判断是部署问题还是契约差异。
probe_and_report() {
  local method="$1" path="$2" hint="$3"
  local out rc
  out="$(zap_call "$method" "$path")"
  rc=$?
  case "$rc" in
    0) ok "$method $path" ;;
    1) param "$method $path$hint" ;;
    *)
      err "$method $path"
      echo "       $(printf '%s' "$out" | tr -d '\n' | head -c 240)"
      ;;
  esac
}

# --------------------------------------------------------------------------- 1. 版本契约
echo "== 1. /JSON/core/about（平台连接器靠它读版本）=="
ABOUT_RAW="$(zap_call GET "/JSON/core/about")"
ABOUT_RC=$?
if [ "$ABOUT_RC" -eq 0 ]; then
  ok "about 连通且响应结构正常"
elif [ "$ABOUT_RC" -eq 1 ]; then
  param "about 返回 200 但含 error 键"
else
  err "about 连通失败"
fi
echo "----- about 原文 -----"
printf '%s\n' "$ABOUT_RAW" | head -c 600
echo
echo "----------------------"
# ⚠️ 已知风险：平台连接器读的是 body["version"]（connector.py 的 _about）。
# 真实 ZAP 的 /JSON/core/about 很可能返回 "zap" 字段而不是 "version"，
# 如果是这样，平台会报「ZAP 返回了非预期的 about 响应」或版本判为不受支持。
# 那是**代码**问题，不是部署问题。
if printf '%s' "$ABOUT_RAW" | grep -q '"version"'; then
  ok '响应含 "version" 字段（与平台契约一致）'
else
  if printf '%s' "$ABOUT_RAW" | grep -q '"zap"'; then
    err '响应用 "zap" 而非 "version" 承载版本：需修 connector._about()，不要改本脚本'
  else
    param '响应里既无 "version" 也无 "zap"，请对照原文判断'
  fi
fi
if VERSION_TEXT="$(printf '%s' "$ABOUT_RAW" | sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"; then
  if [ -n "$VERSION_TEXT" ]; then
    echo "检测到版本：${VERSION_TEXT}"
    if [ "$VERSION_TEXT" != "$MIN_VERSION" ] && \
       [ "$(printf '%s\n%s\n' "$MIN_VERSION" "$VERSION_TEXT" | sort -V | head -1)" = "$MIN_VERSION" ]; then
      ok "版本满足最低要求（>= ${MIN_VERSION}）"
    else
      err "版本低于最低要求 ${MIN_VERSION}"
    fi
  fi
fi
echo

# --------------------------------------------------------------------------- 2. 只读能力探针
echo "== 2. 只读能力探针（对应 connector.get_capabilities）=="
PROBE_GET=(
  "/JSON/core/urls"
  "/JSON/core/history"
)
PROBE_POST=(
  "/JSON/scannerpool/list"
  "/JSON/ascan/getAttackPolicy"
  "/JSON/ascan/progress"
  "/JSON/spider/isRunning"
  "/JSON/clientspider/isClientSpiderRunning"
  "/JSON/pscan/progress"
  "/JSON/pscan/getActiveRules"
  "/JSON/pscan/isAlertOn"
)
for path in "${PROBE_GET[@]}"; do
  probe_and_report GET "$path" ""
done
for path in "${PROBE_POST[@]}"; do
  probe_and_report POST "$path" "（无扫描在跑时返回 error 属正常）"
done
echo

# --------------------------------------------------------------------------- 3. 写入型端点
echo "== 3. 写入型端点（会真的修改 ZAP 全局配置）=="
if [ "$WITH_WRITES" != "1" ]; then
  echo "  跳过。这一组会写入 ZAP 全局配置（scope / 规则开关 / 认证会话），"
  echo "  默认不执行以免干扰正在使用的 ZAP 实例。确认 ZAP 独占后可用："
  echo "    WITH_WRITES=1 $0"
  echo
else
  WRITE_POST=(
    "/JSON/core/setTargetInScope"
    "/JSON/core/setTargetExcludeFromScanRegex"
    "/JSON/core/setOptionInScopeOnlyScan"
    "/JSON/ascan/setConcurrency"
    "/JSON/ascan/setRequestTimingInMs"
    "/JSON/ascan/setMaxDurationInMinutes"
    "/JSON/ascan/setDefaultRuleThreshold"
    "/JSON/authentication/setAuthenticationMethod"
    "/JSON/session/setSessionManagementMethod"
    "/JSON/pscan/setMode"
    "/JSON/openapi/add"
  )
  echo "  ⚠️  以下调用会用**空/最小参数**写入，ZAP 多数会以 error 键拒绝"
  echo "     而不是 500；PARAMS 表示端点存在、参数被拒，属于预期结果。"
  echo
  for path in "${WRITE_POST[@]}"; do
    out="$(zap_call POST "$path")"; rc=$?
    case "$rc" in
      0) ok "POST ${path}（意外成功：请确认参数是否真的生效）" ;;
      1) ok "POST ${path}（端点存在，参数被拒——符合预期）" ;;
      *) err "POST ${path}（非 200：端点可能不存在）"; echo "$out" | head -c 300 ;;
    esac
  done
fi
echo

# --------------------------------------------------------------------------- 4. 汇总
echo "============================================================="
printf '结果：OK %d / PARAMS %d / ERROR %d\n' "$OK" "$PARAMS" "$ERR"
echo "============================================================="
echo
if [ "$ERR" -gt 0 ]; then
  echo "存在 ERROR 项。请区分两类原因："
  echo "  A. 部署问题：地址不对、需要 API Key、端口未映射 → 修部署；"
  echo "  B. 契约不匹配：真实 ZAP 的响应形态与平台连接器假设不同"
  echo "     （最常见：/JSON/core/about 返回 \"zap\" 而非 \"version\"）→ 修代码。"
  echo "  无论哪一类，都要如实回填交付报告，不能在这里替部署方判断。"
  exit 1
fi
echo "无 ERROR 项。PARAMS 项大多是无扫描在跑时的正常结果；"
echo "若要确认真实扫描链路，还需要一次端到端冒烟（见下方说明）。"
echo
echo "端到端冒烟（本脚本**不**做，因为它需要真实授权目标）："
echo "  平台侧：/api/v1/security/zap/capabilities 与 /api/v1/security/zap/health"
echo "  再对一个已授权的测试目标发起一次被动扫描，确认："
echo "    1) 任务能从 PENDING 走到 COMPLETED；"
echo "    2) /alerts 返回的告警带 rule_id 且 severity/confidence 未被混用；"
echo "    3) /findings 里每条都是 Potential Finding（不是确认漏洞）；"
echo "    4) /coverage 的 URL 已脱敏，不含 token / cookie；"
echo "    5) 事件表里没有任何明文 JWT 或 ZAP API Key。"
exit 0
