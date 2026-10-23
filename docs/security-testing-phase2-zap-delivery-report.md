# Security Testing Phase 2 · OWASP ZAP 集成交付报告

> **交付日期**：2026-10-21
> **交付分支**：`feature/security-testing-zap`
> **前置阶段**：Security Testing Phase 1（安全测试用例 / 执行 / Finding / 报告 + 飞书通知）

---

## 0. 一句话结论

Phase 2 的后端能力、数据模型、异步执行、范围守卫、脱敏、Agent 人工批准闸门与前端界面**均已实现并通过 212 条专项测试**；
但**代码从未在真实 OWASP ZAP 实例上运行过**（开发环境无 Docker daemon，全部单测跑在仓库自带 Mock 连接器上），
因此本阶段的正确结论是：

> ### 总判定：**条件通过（CONDITIONAL PASS）**
>
> 平台侧代码完成、可交付、可部署；**集成链路未经真实 ZAP 验证**，
> 必须按 [`docs/zap/README.md`](zap/README.md) 完成部署验证后才能视为整体闭环。
>
> 按「未实现或未验证的核心功能不允许简单标记 PASS」的口径，
> 「真实 ZAP 端到端」一项明确记为 **NOT PASS（未验证）**。

---

## 1. 验证边界（请先读这一节）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 后端 971 条测试 | ✅ 通过 | 含 212 条 Phase 2 专项 |
| 前端 `tsc -b --noEmit` | ✅ 0 错误 | |
| 真实 ZAP 实例 | ❌ **未验证** | 无 Docker daemon，未执行过一次真实扫描 |
| 真实飞书推送 | ❌ **未验证** | 需要真实 webhook（Phase 1 已有该能力，Phase 2 未新增链路） |
| 部署文档 | ✅ 已交付 | [`docs/zap/README.md`](zap/README.md) |
| 冒烟验证脚本 | ✅ 已交付 | [`docs/zap/zap_smoke_check.sh`](zap/zap_smoke_check.sh)，三态判定逻辑已用本地假 ZAP 跑通 |

**为什么不能把「真实 ZAP 端到端」算作 PASS**：Phase 2 的连接器与 Mock 连接器都是同一批人写的，
Mock 的行为是**按连接器的假设**实现的，所以「单测全绿」只能证明平台侧逻辑自洽，
不能证明 ZAP 的真实响应形态与连接器的假设一致。

已知至少有一处**高概率不一致**（详见 §14.1）：平台读 `/JSON/core/about` 的 `version` 字段，
而真实 ZAP 很可能返回 `zap` 字段。

---

## 2. 阶段范围

### 2.1 本期做

- 外部 ZAP 实例对接（REST API + API Key，凭据只存 Fernet 密文）
- 扫描目标 / 扫描策略 / 认证配置三类项目级配置（含 6 个平台内置策略）
- 范围守卫（SSRF 防护、生产环境禁止主动扫描、主动扫描默认排除高危路径）
- DB 支撑的异步任务生命周期（不依赖 FastAPI BackgroundTasks 或进程内字典）
- 能力探测与「如实标记受限」
- 证据脱敏（不落原始 Request/Response）
- Finding 指纹与 Potential Finding 模型
- 任务结果查询（进度 / 事件 / 告警 / 覆盖率 / 报告）
- Agent 发起扫描的**人工批准闸门**
- 前端安全扫描 Tab（4 个子 Tab）
- 部署文档与冒烟脚本

### 2.2 本期明确不做

| 不做的事 | 原因 |
| --- | --- |
| Web UI Automation / Mobile Automation / Performance Testing | 需求明确禁止本期启动 |
| 重建第二套 Security Finding / TestRun / Agent / Report / 权限系统 | 需求红线 |
| 支付 / 删除 / 批量修改类主动扫描的二次授权流程 | Phase 2 直接拒绝，不实现二次授权 |
| 飞书扫码等人工登录的自动化 | 部署环境无人工浏览器交互时**如实标记为无法验证** |
| 大规模调度平台 | `ZAP_MAX_CONCURRENT_JOBS=1`，单实例串行 |
| 扫描结果推送到飞书通知 | **本期未实现**，见 §13 |
| 报告层把扫描任务聚合进平台 TestReport | **本期未实现**，见 §13 |

---

## 3. 架构与分层

```
前端 ZapScanTab
      │  REST（/api/v1/projects/{pid}/security/...）
      ▼
router.py ──────────── 只处理协议、鉴权、分页；不拼任何 ZAP 请求
      │
      ▼
services/*_service.py ── 权限、环境、授权闸门、计划预览、任务登记
      │
      ├──▶ scope_guard.py   所有扫描请求发出前的范围限制（唯一入口）
      │
      ▼
worker.py ── 独立轮询线程，DB 领取任务（原子 UPDATE ... WHERE status=...）
      │
      ▼
orchestrator.py ── 阶段编排（PREPARING / SCANNING / COLLECTING / ...）
      │
      ▼
connector.py ── ZAP 语义封装（apply_scope / run_spider / run_active_scan / ...）
      │
      ▼
transport.py ── HTTP 传输（httpx，trust_env=False，统一超时与重试）
      │
      ▼
mock.py ── 同接口的 Mock 实现（单测用，与 transport 接口一致）
```

关键约束落实情况：

- **Router 不直接拼 ZAP 请求** ✅ `router.py` 里没有任何 `/JSON/...` 字面量，
  全部经 `services` → `connector` 下发。
- **ZAP 响应转换成平台内部 Schema** ✅ `contracts.py` 里定义了
  `ZAPAbout` / `ZAPCapability` / `ZAPAlert` / `ZAPCoverage` 等 dataclass，
  connector 返回平台结构，业务层不接触 ZAP 原始 JSON。
- **不建第二套 TestRun / Report / 权限** ✅ Finding 本体复用 Phase 1 的
  `security_finding` 表；`security_scan_finding` 只是关系表
  （`finding_id FK → security_finding.id`）。权限复用 `_access` 层。
- **不伪造 CaseExecution** ✅ 全 feature 里没有任何 `CaseExecution` 的写入路径。

---

## 4. 数据模型与迁移

**新增 6 张表**（迁移 [`backend/alembic/versions/0013_zap_security_scan.py`](../backend/alembic/versions/0013_zap_security_scan.py)）：

| 表 | 作用 |
| --- | --- |
| `security_scan_target` | 扫描目标：base_url / entry_url / allowed_hosts / 授权状态 |
| `security_scan_profile` | 扫描策略：扫描模式、深度、并发、时长、规则集（含 6 个平台内置） |
| `security_scan_auth_profile` | 认证配置：**凭据只存 Fernet 密文，接口永不回显** |
| `security_scan_job` | 扫描任务（异步执行的唯一事实源） |
| `security_scan_finding` | 任务 ↔ `security_finding` 多对多关系 |
| `security_scan_event` | 过程事件（脱敏），供详情页时间线 |

迁移红线遵守情况：

- `revision = "0013"`，`down_revision = "0012"`，**未修改任何历史版本** ✅
- 全部用显式 `op.create_table` / `op.add_column`，未使用 `Base.metadata.create_all` ✅
- 带幂等保护（表存在则跳过）✅
- 未把新表 import 进 `app/models/__init__.py` ✅

---

## 5. 扫描任务生命周期（§八）

| 要求 | 实现 |
| --- | --- |
| 禁止在 FastAPI 请求中同步等待 | `POST /scan-jobs` 立即返回 202 + `PENDING`；执行在独立线程 |
| 禁止仅靠 BackgroundTasks / 进程内字典 | 任务状态完全在 DB（`security_scan_job` + `security_scan_event`） |
| 服务重启后恢复或标记中断 | 心跳超时 `ZAP_HEARTBEAT_TIMEOUT_SECONDS=180`，启动时扫描 stale 任务并标记中断 |
| 防止重复领取 | 原子领取：`UPDATE ... SET status='RUNNING' WHERE id=:id AND status='PENDING'`，看影响行数 |
| 并发限制 | `ZAP_MAX_CONCURRENT_JOBS=1`；同一目标已有 `PENDING`/`RUNNING` 直接 409 |
| 同一 ZAP 实例同一时间只执行一个需修改全局配置的任务 | 由 `MAX_CONCURRENT_JOBS=1` 保证；`apply_scope` 会写 ZAP 全局 scope 设置 |
| 取消 | `POST /scan-jobs/{id}/cancel` 只置位 `cancel_requested`，Worker 在下一个检查点真正停止 |

---

## 6. 范围守卫与 SSRF（§三十四）

范围限制落在**后端唯一入口** `scope_guard.py`，且**在三个时点**各自独立执行一次：

1. **写入配置时**（`target_service._validate_base_and_entry`）—— 创建/修改目标就拦；
2. **登记任务时**（`job_service.plan` / `job_service.create`）—— 预览与提交各自校验；
3. **执行开始时**（`orchestrator._stage_preparing`）—— 创建到执行之间配置可能变，再校验一次。

覆盖的绕过路径：

- **DNS 变化 / 保留地址**：`resolve_host_ips` → `is_reachable_public_ip`，
  回环 / 私网 / 链路本地 / 保留 / 组播 / 未指定 / 云元数据 169.254.169.254 全部拒绝；
  **只放行明确的公网地址**。
- **数字形态 IP 绕过**：`_looks_numeric_ip` 按「每一个点分段都能被当成数字段」判定，
  覆盖 `0177.0.0.1`（八进制）、`0x7f000001`（十六进制）、`2130706433`、`127.1` 等
  `ipaddress` 不认但系统解析器会认的写法（不同平台结果不同，必须直接拒绝）。
- **重定向**：`assert_redirect_allowed` 重新走同一套校验；未配 allowed_hosts 时收紧到「与扫描根同主机」。
- **代理出口**：传输层 `trust_env=False`，不走系统代理。
- **正则注入**：`compile_path_regex` / `default_active_exclude_regex` 对路径全量 `re.escape`。
- **白名单条目被静默丢弃**：`_normalize_host_set` / `_normalize_host_port_set` 对「非空但解析不出主机名」
  的条目直接报 `SECURITY_SCAN_SCOPE_VIOLATION`（见 §14.2）。

生产环境与主动扫描：

- `is_production_environment` 按分隔符切词 + 中文子串匹配（「生产环境」「线上环境」都能命中）；
  `prod01` / `production1` 这类序号后缀也按生产处理。
- **Production 禁止主动扫描**：`assert_active_scan_authorized` 抛
  `CODE_SECURITY_SCAN_PRODUCTION_FORBIDDEN`（403）。
- **主动扫描四关**（`job_service.create`，全部服务端计算，不信任客户端参数）：
  admin 权限 → 环境允许主动 → 目标 `authorization_status == AUTHORIZED` → 显式确认 + 批准说明。
- **默认低强度**：未配排除路径时自动排除 `HIGH_RISK_ACTIVE_PATH_PATTERNS`
  （logout / delete / payment / transfer / withdraw / refund / production / ...），
  并在计划预览里如实列出这条限制。危险路径**只是候选**，不能仅凭路径字符串认定安全。
- **破坏性方法默认不发**：`DESTRUCTIVE_METHODS = {DELETE, PATCH, PUT, OPTIONS, TRACE, CONNECT}`。

---

## 7. 证据脱敏（§二十一、§三十四 第 8 条）

原始 Request/Response **不落库**，只存脱敏后的结构化字段：

- `redact_mapping`：递归脱敏 dict / list，敏感键整值替换为 `******`，
  超长字符串截断并带可见标记，列表条目有 `MAX_EVIDENCE_ITEMS` 硬上限；
- `redact_text`：抹 `Bearer <token>` / `Authorization: *** / `Cookie: ******` 三类头回显；
- `redact_url`：抹 query 里的凭据参数值，**保留参数名**（指纹依赖参数名）；
- **证据签名在脱敏之后计算**（`evidence_signature(redacted_evidence)`），
  所以指纹建立在已脱敏 URL 上，同一注入点不会因令牌不同散成多条。

脱敏只做两件事：按**键名**判敏感（`SENSITIVE_FIELD_NAMES`），或按**已知值形态**
（JWT / Bearer / webhook）。不猜其它形态——「只认键名不认值」是刻意口径，
JWT 长串无法靠形态可靠识别。

⚠️ 本节修复了两个真实凭据泄漏漏洞，见 §14.3 与 §14.4。

---

## 8. Finding 与指纹（§十八、§十九、§二十）

- **保留规则原始 ID**：`ZAPAlert.rule_id` 原样入 `security_finding.source_rule_id`，不映射、不合并。
- **Confidence 与 Severity 是两个独立维度**：`ZAPAlert.confidence`（1–5 整数，越界收边界）
  与 `ZAPAlert.severity`（LOW/MEDIUM/HIGH）分列存储，**不做任何互转**。
- **告警先作为 Potential Finding**：新告警统一落 `POTENTIAL`，
  没有任何路径把 ZAP 告警直接判定为确认漏洞。
- **人工确认状态不因重扫重置**：复用 Phase 1 的 `security_finding` 部分唯一索引与
  `status` / `verified_by` / `verified_at` 字段；`security_scan_finding` 关系表
  只做「本次扫描又观察到这条」的记录，**不触碰**人工确认字段。

指纹（`normalizer.build_fingerprint`）：

```
sha256( "zap" | project_id | target_id | rule_id | normalized_url | parameter | evidence_signature )
```

- 含 `target_id`：不同项目/目标不串号；
- **不含 `job_id`**：跨次扫描能识别同一问题；
- `normalized_url` 是**脱敏后**的 URL，`evidence_signature` 是脱敏证据的前 12 位。

---

## 9. Agent 人工批准闸门（§二十三）

这是 Phase 2 最核心的安全设计。

**问题**：`job_service.create` 的 `confirmed` 是普通布尔字段。
如果让 LLM 直接调创建工具，模型只要幻觉出 `confirmed=true` 加一句编造的
`approval_note`，就能通过全部校验——而这恰恰是 §二十三 禁止的。

**解法**：把「确认」从一个**可被 LLM 伪造的参数**，改成一次**只能由人类触发的图路由事件**。
四层独立闸门：

| 层 | 机制 |
| --- | --- |
| 1. 工具层 | LLM 侧**没有**创建任务的工具；`preview_scan` 恒传 `confirmed=False`，且预览不写库、不发 ZAP 请求 |
| 2. 路由层 | `route_entry` 只在 `action == "confirm_security_scan"` 时进入 `zap_scan_job_creator`，而 LLM 的工具参数里没有这个 action |
| 3. 节点层 | 节点内再断言一次 `state["action"] == CONFIRM_ACTION`，并把结论传给工具的 `human_approved` |
| 4. 服务层 | `job_service.create` 独立再校验权限 / 环境 / 目标授权 / 确认 / 批准说明五关 |

额外两条：

- **批准说明只从 `action_payload` 读**（人工在确认弹窗里填的），
  绝不从 LLM 可写的 state 取。
- **`approval_note` 不写入消息历史、不写入 agent_message 内容、不写入 metadata**——
  因为 `state["messages"]` 会被当 `history` 喂给下一轮 LLM，
  写进去就等于让模型看到人类的批准理由。
- **计划一致性复核**：确认时重新算一次计划，如果预览时是被动、此刻已是主动，
  直接拒绝（`SECURITY_SCAN_NOT_AUTHORIZED`）——不能用一次被动确认放行主动扫描。

**不交给 LLM 决定扫描范围**：`IntentResult` 里没有 LLM 可写的目标/策略 ID 字段。
目标与策略由前端下拉框指定（`zap_scan_target_id` / `zap_scan_profile_id`），
或仅在「项目内恰好只有一个启用选项」时自动选用，否则返回 `CLARIFY` 澄清。
这样才满足 §三十四「不允许 Agent 自动扩大扫描范围」。

---

## 10. 能力探测与「如实标记受限」

- `GET /security/zap/capabilities` 只走 `about` / `isRunning` / `get*` 等**只读**接口，绝不触发扫描；
- 缺 `spider` / `passive` / `active` / `history` 任何一个，扫描在 PREPARING 阶段
  以 `ZAP_PLUGIN_MISSING` 明确失败；
- 计划预览的 `limitations` 列表如实列出所有受限项，包括：
  ZAP 未启用、未配 API Key、目标未开主动扫描、目标授权状态不对、需要确认、
  浏览器登录态建不起来、飞书扫码不支持、策略既没开被动也没开主动；
- **`ZAP_AUTH_MODE=MANUAL`（飞书扫码等）时如实标记「无法验证」**，
  绝不把无法复现的认证过程记为成功；
- **配了 `Authorization` Header 不等于 SPA 已登录**：SPA 只认 Cookie，
  计划会提示「只能扫到登录前内容」，`browser_session_established` 显式为 false。

⚠️ 一个字段名容易被误读：`GET /security/zap/health` 的 `reachable` **不表示网络真的通了**，
它的取值是 `ZAP_ENABLED and ZAP_BASE_URL 非空`，只是「配置齐了」；
该端点也不发起网络请求，`version` 恒为 `null`。连通性只能靠 §11 的验证脚本确认。

---

## 11. 前端

新增（`frontend/src/pages/console/SecurityTesting/`）：

| 文件 | 内容 |
| --- | --- |
| `ZapScanTab.tsx` | 第 5 个顶层 Tab，内含 4 个子 Tab |
| `zap/targets.tsx` | 扫描目标 CRUD，列表带授权状态 / 主动扫描 / 生产环境徽标 |
| `zap/policies.tsx` | 扫描策略 + 认证配置；**平台内置策略全字段只读** |
| `zap/jobs.tsx` | 任务列表 + 状态过滤 + 取消 |
| `zap/wizard.tsx` | 发起扫描四步向导 |
| `zap/results.tsx` | 按任务看结果 |
| `zap/jobDetail.tsx` / `zap/jobPanels.tsx` | 任务详情与事件/告警/覆盖率/报告面板 |
| `zap/constants.ts` | 标签与颜色映射 |

四步向导的把关逻辑：

1. 选目标（只列启用的）→ 2. 选策略与认证（认证绑定在策略上，不能单独选）
   → 3. 授权确认 → 4. 计划预览并提交；
2. 第 4 步必须先调 `POST /scan-jobs/plan` 拿到预览，**预览没成功「提交扫描」不可点**；
3. 主动扫描在第 3 步必须勾选确认**并填写批准说明**，缺说明直接不给下一步；
4. 预览里如实展示 `production_blocked` / `limitations` / `zap_available`，
   被拒的计划提交按钮禁用；
5. 预览为空限制项时会额外提示「这不等于 ZAP 服务一定在线」——
   避免把「没被拒绝任何能力」误读成「ZAP 已连通」。

`npx tsc -b --noEmit`：**0 错误**。

⚠️ 本期修掉一处**误导性文案**：目标表单原本提示 `如 http://10.0.0.12:8080`，
而后端 scope_guard 会拒绝所有私网地址（§6）。已改为公网示例并加了一条明确的限制说明。

---

## 12. 测试

### 12.1 新增专项测试

| 文件 | 用例数 | 覆盖 |
| --- | --- | --- |
| `tests/test_28_zap_connector.py` | 96 | 连接器、传输、Mock、能力探测、连接器错误分类 |
| `tests/test_29_zap_scan.py` | 99 | 范围守卫、SSRF、策略、任务生命周期、脱敏、指纹、正常化 |
| `tests/test_32_zap_agent_approval.py` | 17 | Agent 人工批准闸门（工具层 / 图路由 / 节点 / 服务四层） |
| **合计** | **212** | |

`test_32` 的关键用例：

- `test_create_refused_without_human_approval`：`human_approved=False` 在进 service 之前就被拒，且库里没有任务；
- `test_preview_never_confirms_and_writes_nothing`：预览恒 `confirmed=False`，不写库、不带 `approval_note`；
- `test_llm_hallucinated_confirmation_is_ignored`：把 `confirmed=True` + 编造的 `approval_note` 塞进 LLM 输出，
  字段被丢弃、图停在 `ZAP_SCAN_REVIEW`、任务数为 0；
- `test_llm_approval_note_never_reaches_prompt_history`：人工批准说明不出现在下一轮 LLM 的 `history` 里；
- `test_active_confirm_without_note_is_refused` / `test_active_confirm_with_note_records_approver`：
  批准说明必填、`approved_by = 确认人`；
- `test_plan_upgraded_to_active_after_review_is_refused`：被动预览不能放行主动扫描；
- `test_cross_project_target_is_404`：跨项目目标返回 404 而非 403（不泄露存在性）；
- `test_multiple_targets_returns_clarify_not_guess` / `test_explicit_target_id_bypasses_ambiguity`：
  范围有歧义时澄清而不是猜。

### 12.2 全量结果

```
tests/ 全量：971 passed, 1 failed
```

唯一失败项：

```
FAILED tests/test_31_web_ui_console.py::test_real_console_create_confirm_debug_report
  E  playwright TimeoutError: waiting for get_by_role("tab", name="逐用例执行")
```

**该项与本阶段无关，未修改**：它属于并行的 Web UI Automation 工作线
（当前工作分支 `codex/web-ui-automation-phase1`），等待的是一个 Phase 1 尚未交付的
「逐用例执行」Tab。按「不要自行开始 Web UI Automation」的约束，本报告不触碰、
也不替它宣称通过。

---

## 13. 未实现项与功能限制（请重点看这一节）

### 13.1 报告层未聚合扫描任务 ❌

需求要求「通过报告层统一聚合」。现状：

- 代码注释里写了「报告层用 SecurityScanJob + TestRun 统一聚合」
  （`orchestrator.py`、`models/job.py`）；
- 但 `app/features/reports/` 下**没有任何一处**引用 `SecurityScanJob` 或扫描任务；
- 扫描结果目前只有**独立的** `GET /scan-jobs/{id}/report`，
  不进入平台统一的 `TestReport`。

**这是本期最实的一个缺口**。已实现的半边是安全的：
没有伪造 `CaseExecution`、没有破坏 `TestRun`（§二十二 前两项达标），
但「聚合」这一步没做。**不能标 PASS。**

### 13.2 扫描结果未推送飞书 ❌

Phase 1 已有 `FeishuNotificationService`，但它只接受 `TestReport`。
本期没有为 `ScanReportRead` 写适配器，因此扫描任务完成后**不会**触发飞书通知。
需求 §三十 附近的报告通知要求，对 ZAP 扫描链路**本期未闭环**。

### 13.3 内网测试环境扫不到 ⚠️

为防 SSRF，`is_reachable_public_ip` **只放行解析到公网地址的目标**，
`10.x` / `192.168.x` / `172.16-31.x` 等私网与保留地址一律拒绝
（创建扫描目标时即 403，且已有测试钉住该行为）。

代价是「授权的内网测试环境」这个最常见场景一期覆盖不到。
正确解法是新增「授权私网段白名单」并让 scope_guard 区分「被授权的私网」与「任意私网」；
**不要**为了覆盖内网而直接放宽 `is_reachable_public_ip`——那等于把扫描器变成 SSRF 出口。

### 13.4 真实 ZAP 未验证 ❌

见 §1。另有一处**高概率契约不一致**，见 §14.1。

### 13.5 其余已知限制

1. **不做支付 / 删除 / 批量修改的二次授权**：`BLOCKED_ACTIVE_ACTIONS` 直接拒绝，没有二次授权流程；
2. **不做飞书扫码自动化**：`AUTH_MODE_MANUAL` 如实标记「无法验证」；
3. **单实例串行**：`ZAP_MAX_CONCURRENT_JOBS=1`；
4. **不实现扫描任务的重新排队**：中断的任务只标记状态，不会自动重试。

---

## 14. 本期发现并修复的缺陷（全部有回归测试）

按严重度排列。这些都是**安全相关的真实漏洞**，不是风格问题。

### 14.1 严重：十六进制 IP 绕过 SSRF 检查 —— 已修复

`scope_guard._looks_numeric_ip` 原本有一个前置过滤 `re.search(r"[g-z]", text)`，
用于「整串不含 g–z 字母才算数字形态」。

**问题**：十六进制前缀 `0x` 里的字面 `x` 正好落在 g–z 区间，
所以 `0x7f000001`（= 127.0.0.1）、`127.0x1` 这类写法被误判成普通域名，
被交给系统解析器——而系统解析器会按数字形态解析它们，**不同平台结果还不同**
（macOS 把 `0177.0.0.1` 解成 `177.0.0.1` 这个公网地址，Linux 解成 `127.0.0.1`）。
放行后扫描实际打到哪个地址完全取决于目标机器装了什么解析器。

**修复**：删掉该前置过滤，改成「每一个点分段都能匹配数字段正则
`^(0x[0-9a-f]+|[0-9]+)$`」才算数字形态。

**不会误伤正常域名**：`api.example.com` / `localhost` / `abc123` / `www.a.co`
每个都至少有一个段带字母，匹配不上数字段正则。已由
`test_normal_hostnames_are_not_misclassified_as_numeric` 覆盖。

### 14.2 严重：白名单条目被静默丢弃，扫描范围完全失效 —— 已修复

`_normalize_host_set` / `_normalize_host_port_set` 原本对解析不出主机名的条目 `continue`。

**问题**：`allowed_hosts=["::1"]`（未加方括号的 IPv6）会被拆成空主机名，
条目被静默丢弃，白名单随之变成**空集**——而空集在 `validate_target_url` 里
等于「不做任何主机限制」。管理员声明过的扫描范围从这一刻起完全失效。

**修复**：新增 `_host_port_or_raise` / `_host_or_raise`，
对「非空但解析不出主机名」的条目抛 `SECURITY_SCAN_SCOPE_VIOLATION`；
`None` / 空串仍按「未填写」处理（管理员留空一格是常见情况）。

### 14.3 严重：`x-zap-api-key` / `set-cookie` 等键名完全没被脱敏 —— 已修复

`SENSITIVE_FIELD_NAMES` 里带连字符的条目**永远匹配不上**，
它们的连字符 / 下划线 / 大小写变体全部原样落库。

**根因**：`_redact_key` 只对**输入键名**把连字符换成下划线
（`x-zap-api-key` → `x_zap_api_key`），
而集合条目只去空格不去连字符（`x-zap-api-key` 仍是 `x-zap-api-key`）。
两侧口径不一致，比较必然失败。

命中失败的键名（`redact_value` 直接返回原值）：

```
x-zap-api-key, X-ZAP-API-Key, x_zap_api_key, xZapApiKey,
Set-Cookie, set-cookie, set_cookie, ...
```

也就是说 ZAP 自己的 API Key 头（请求头回显里的标准形态）与响应 Set-Cookie
在告警 evidence 里都是明文落库的。

**修复**：抽出唯一口径 `_canonical_key`（剥掉所有非字母数字字符后小写），
两侧统一走它，并预生成 `SENSITIVE_KEY_CANONICAL` 做 O(1) 查表：

```python
_NON_NAME_CHAR = re.compile(r"[^a-z0-9]")

def _canonical_key(name):
    return _NON_NAME_CHAR.sub("", str(name).lower())

SENSITIVE_KEY_CANONICAL = frozenset(_canonical_key(n) for n in SENSITIVE_FIELD_NAMES)

def _redact_key(key):
    if key is None:
        return False
    return _canonical_key(key) in SENSITIVE_KEY_CANONICAL
```

**取舍（刻意接受过度脱敏）**：这个口径会连带把空格写法并入
（`accesstoken` 与 `access_token` 同形）。结果是某些非敏感字段可能被多脱敏一点，
只影响可读性，**不会造成凭据外泄**——比漏脱敏划算。已在函数 docstring 里写明。

### 14.4 中等：URL 里的 `?client-secret=` 泄漏 —— 已修复

同类问题在 `redact_url`：原本用 `key.lower() in URL_CREDENTIAL_KEYS` 精确比较，
所以 `?access-token=` / `?client-secret=` 这类连字符写法会被放行，
而 `?access_token=` / `?client_secret=` 会被掩码——同一条凭据两种拼写待遇不同。

**修复**：URL 侧同样用 `_canonical_key` + `URL_CREDENTIAL_KEY_CANONICAL`。
键名集合本身**没有放宽**（保持刻意窄：`timestamp` / `sign` 之类在 URL 里通常是业务参数）。
`tokenize` / `tokens` 等后缀词不会被误判——归一化只剥分隔符，不做子串匹配。

### 14.5 轻微：前端提示用户填写会被后端拒绝的地址 —— 已修复

目标表单原本提示 `如 http://10.0.0.12:8080`，
而后端拒绝所有私网地址（§13.3）。用户照着填必然失败，且看不出原因。
已改为公网示例，并加了一条 Alert 说明「内网地址目前会被后端直接拒绝」及其原因。
同时修正了 `scope_guard.ALLOWED_SCHEMES` 上一条已经不准确的注释。

### 14.6 轻微：Agent 侧错误码不一致 —— 已修复

`zap_scan_planner_node` 的 `except AppError` 分支原来直接用平台原始错误码
（`CODE_SECURITY_SCAN_TARGET_NOT_FOUND`），
而 `except HTTPException` 分支映射成 `TARGET_NOT_FOUND`——同一类错误两条路径给出两个码。
已统一走 `_code_of`（与 Phase F 的 security 节点一致）。

---

## 15. 部署与运维

完整说明见 [`docs/zap/README.md`](zap/README.md)。要点：

- ZAP 必须以官方 `owasp/zap2docker-stable` 镜像跑在容器网络里；
- **ZAP 管理 API 绝不能对公网开放**（该 API 无登录态，暴露等于让公网借你的实例扫描别人）；
  推荐私有 bridge 网络且不发布端口；平台跑在宿主机时只能绑 `127.0.0.1`；
- 平台最低版本要求 **ZAP ≥ 2.12.0**；
- `ZAP_ENABLED=false` 是默认值，false 时任务登记但永不运行，健康检查如实返回不可用；
- API Key 只存 Fernet 密文，`ZAP_API_KEY_MODE=header` 走 `X-ZAP-API-Key`
  （`query` 方式会进日志，不推荐）；
- 回滚：`ZAP_ENABLED=false` + 清掉 `ZAP_BASE_URL` / `ZAP_API_KEY_ENCRYPTED`；
  迁移是新增的，不需要回滚表结构。

---

## 16. 13 项交付判定

| # | 判定项 | 结论 |
| --- | --- | --- |
| 1 | ZAP 实例对接（REST + API Key 密文，凭据不明文入库/进日志/进 Prompt） | **PASS** |
| 2 | Router 不拼 ZAP 请求，响应统一转平台 Schema | **PASS** |
| 3 | DB 支撑的异步执行，不依赖 BackgroundTasks / 进程内字典，重启可恢复 | **PASS** |
| 4 | 防止重复领取、并发限制、取消语义 | **PASS** |
| 5 | 扫描前范围限制落在后端（写入 / 计划 / 执行三个时点） | **PASS** |
| 6 | SSRF 防护（保留地址 / 数字形态 IP / 重定向 / 代理 / 正则注入 / 白名单静默丢弃） | **PASS** |
| 7 | 生产环境禁止主动扫描；主动扫描权限/环境/授权/确认四关 | **PASS** |
| 8 | 主动扫描人工批准不可被 LLM 伪造（四层独立闸门） | **PASS** |
| 9 | 证据脱敏（含连字符键名变体、URL 连字符参数） | **PASS** |
| 10 | 告警先作 Potential Finding；Confidence/Severity 不混用；重扫不重置人工确认 | **PASS** |
| 11 | 指纹符合 `project+target+scanner+rule_id+normalized_url+parameter+evidence_signature` | **PASS** |
| 12 | 不伪造 CaseExecution、不破坏 TestRun、不建第二套 Finding/Report/权限 | **PASS**（但见第 13 项） |
| 13 | **真实 ZAP 端到端验证 + 报告层聚合 + 飞书通知闭环** | **NOT PASS** |

### 16.1 关于第 13 项的说明

这一项里三件事，只有第一件是「未验证」，后两件是「未实现」：

- **真实 ZAP 端到端**：**未验证**。代码可能正确，但无人证明。
  已交付 `docs/zap/zap_smoke_check.sh` 与部署文档，验证入口是齐的；
  执行这件事必须在有 Docker 的环境里做。
- **报告层聚合**：**未实现**。`app/features/reports/` 无任何扫描任务引用（§13.1）。
- **飞书通知闭环**：**未实现**。无 `ScanReportRead` → `FeishuNotificationService` 适配器（§13.2）。

按「如果存在未实现或未验证的核心功能，不允许简单标记 PASS」的口径，
这一项必须记 **NOT PASS**，不能用「其余 12 项都过」来抵消。

---

## 17. 总判定

> # **条件通过（CONDITIONAL PASS）**
>
> 平台侧代码完成度：可交付。12 / 13 项达标，全部安全红线（范围限制、
> 生产环境禁扫、主动扫描人工批准不可伪造、凭据不落库、告警不作确认漏洞）
> 均有实现且有回归测试钉住。本期修掉的 4 类安全漏洞中 3 类属于**真实凭据泄漏或 SSRF 绕过**，
> 说明测试覆盖是有效的。
>
> 但**集成链路未经真实 ZAP 验证**，且「报告层聚合」与「飞书通知」两项目前**未实现**。
> 因此不能给「通过」。
>
> **转为完全通过的必要动作**（按优先级）：
> 1. 在有 Docker 的环境里跑 `docs/zap/zap_smoke_check.sh`，
>    先确认 `/JSON/core/about` 的字段名问题（§14 之后的最大风险）；
>    如确认返回 `zap` 而非 `version`，修 `connector._about()` 并同时读两个字段；
> 2. 对一个已授权的非生产测试目标跑一次被动扫描，走完 README §5.2 的 7 条端到端清单；
> 3. 实现 `app/features/reports/` 对扫描任务的聚合（或明确把该项移出本期范围）；
> 4. 实现 `ScanReportRead` → 飞书通知适配器（或明确移出本期范围）；
> 5. 把上述结果回填本报告 §1、§13、§16，再把总判定改为「通过」。

---

## 18. 后续阶段建议

1. **授权私网段白名单**（§13.3）——这是内网测试环境可用的前置条件，
   应当作为独立小阶段做，而不是塞进 ZAP 联调；
2. **报告层聚合**（§13.1）；
3. **飞书通知适配**（§13.2）；
4. **连接器契约测试**：把「Mock 与真实 ZAP 的响应形态差异」做成一个
   可勾选的契约检查表（冒烟脚本的三态结果可以直接回填），
   避免下一批 ZAP API 调用再次只靠 Mock 验证；
5. 支付 / 删除 / 批量修改类主动扫描的**二次授权流程**（本期直接拒绝）。

---

## 附录 A：本期交付物清单

### 后端新增（`app/features/security_testing/zap/`，28 个模块）

```
__init__.py  auth.py  builtins.py  client.py  connector.py  contracts.py
event_log.py  mock.py  normalizer.py  openapi_export.py  orchestrator.py
router.py  schemas.py  scope_guard.py  transport.py  worker.py
models/__init__.py  models/auth_profile.py  models/finding_link.py
models/job.py  models/profile.py  models/target.py
services/__init__.py  services/_access.py  services/auth_profile_service.py
services/job_service.py  services/profile_service.py  services/target_service.py
```

### 后端其它新增 / 修改

```
alembic/versions/0013_zap_security_scan.py        迁移（6 张表）
app/features/agent/nodes/zap_scan.py              三个 Agent 节点
app/features/agent/tools/zap_scan_tool.py         Agent 工具（无创建任务能力）
tests/test_28_zap_connector.py                    96 用例
tests/test_29_zap_scan.py                         99 用例
tests/test_32_zap_agent_approval.py               17 用例
```

修改的既有文件：`agent/graph.py`、`agent/nodes/router.py`、`agent/router.py`、
`agent/schemas.py`、`agent/state.py`、`agent/services/session_service.py`、
`agent/prompts/intent.md`、`agent/tools/__init__.py`、
`shared/config.py`、`shared/errors.py`、`main.py`、`.env.example`，
以及 `test_01` / `test_10` / `test_18` / `test_22` / `test_30`。

### 前端新增 / 修改

```
src/pages/console/SecurityTesting/ZapScanTab.tsx
src/pages/console/SecurityTesting/zap/{targets,policies,jobs,wizard,results,jobDetail,jobPanels,constants}.tsx
src/pages/console/SecurityTesting/index.tsx      接入第 5 个 Tab
src/api/securityTesting.ts                        新增 ZAP API 类型与调用
```

### 文档

```
docs/zap/README.md                    部署与验证
docs/zap/zap_smoke_check.sh           冒烟检查脚本
docs/security-testing-phase2-zap-delivery-report.md    本文
```

---

## 附录 B：需求条目覆盖映射

| 需求条目 | 覆盖情况 |
| --- | --- |
| §四 避免 SSRF | ✅ 三层校验 + 六类绕过路径（§6） |
| §五 Production 禁止主动扫描 | ✅ 环境名判断偏保守 + 计划阶段即拦（§6） |
| §六 Router 不拼 ZAP 请求 / 响应转内部 Schema | ✅（§3） |
| §八 异步执行 / 重启恢复 / 防重复领取 / 并发限制 | ✅（§5） |
| §九 危险路径默认不发 | ✅ `HIGH_RISK_ACTIVE_PATH_PATTERNS` + `DESTRUCTIVE_METHODS`（§6） |
| §十一 凭据不落库 / 不进日志 / 不进 Prompt / 不以 200 判登录 | ✅（§7、§10） |
| §十二 不认为配了 Header 就已登录 | ✅ `browser_session_established` + 计划提示（§10） |
| §十三 不自动绕过飞书扫码 / 无法交互时如实标记 | ✅（§10） |
| §十五 默认低强度 / 不做全量高危 / 范围限制在后端 | ✅（§6） |
| §十八 保留原始 rule_id / Confidence≠Severity / Potential Finding | ✅（§8） |
| §十九 重扫不重置人工确认 | ✅（§8） |
| §二十 指纹公式 | ✅（§8） |
| §二十一 原始 Request/Response 不落库 / 迁移不改历史 | ✅（§4、§7） |
| §二十二 不伪造 CaseExecution | ✅；**报告层聚合 ❌**（§13.1） |
| §二十三 主动扫描需真实人类批准 | ✅ 四层闸门（§9） |
| §二十五 报告数字来自任务记录本身，不重新扫描 | ✅ |
| §三十四 第 1 条 扫描前范围限制 | ✅（§6） |
| §三十四 第 2 条 Production 禁止主动扫描 | ✅ |
| §三十四 第 8 条 日志不存 JWT 和凭据 | ✅ 本期修了两处泄漏（§14.3、§14.4） |
| §三十四「不允许 Agent 自动扩大扫描范围」 | ✅ 目标不由 LLM 决定（§9） |
| §三十四「不允许 ZAP API 对公网开放」 | ⚠️ 由部署约束保证，文档已明确（§15） |
| §三十八 每 Phase 完成跑相关测试 | ✅ 212 条专项 + 全量 971 |
| §三十九 不改历史 Revision / 不写死密钥 / 不启动其它工作线 | ✅ |
| §四十 交付报告 | ✅ 本文 |

---

*本报告中的每一项「已实现」都可以定位到具体文件与测试；
每一项「未实现 / 未验证」都说明了缺口与补齐动作。*
