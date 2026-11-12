export const meta = {
  name: 'api-catalog-gap-fill',
  description: '补跑上轮 429 未运行的 4 个维度（CRUD 服务 / 前后端契约 / 迁移与 ORM / 业务阶段二），并重新对抗性验证 6 条被丢弃的结论',
  phases: [
    { title: 'FindMissing', detail: '串行补跑 4 个盲区维度，避免并发 429' },
    { title: 'Verify', detail: '对抗性反证新结论 + 6 条上轮被丢弃的结论' },
  ],
}

const ROOT = '/Users/a1/Desktop/ai-test-project'

const FINDINGS_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          file: { type: 'string', description: '仓库相对路径' },
          line: { type: 'integer', description: '1 起行号，尽力给出' },
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          title: { type: 'string' },
          failure_scenario: { type: 'string', description: '具体输入 -> 具体错误输出' },
          fix: { type: 'string', description: '最小修复' },
        },
        required: ['file', 'severity', 'title', 'failure_scenario', 'fix'],
      },
    },
    checked: { type: 'string', description: '你实际读了哪些文件、验证了哪些点' },
  },
  required: ['findings', 'checked'],
}

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    real: { type: 'boolean' },
    severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
    reasoning: { type: 'string' },
    fix: { type: 'string' },
  },
  required: ['real', 'severity', 'reasoning', 'fix'],
}

// 并发审查者共享的工具约束：多个 agent 同时跑 pytest 会互相摧毁 testplatform_test 库。
const TOOLING = `工具约束：
- 只读审查：不修改任何文件，不运行 pytest / alembic / npm / git 的写操作（多个审查者并发跑 pytest 会互相摧毁 testplatform_test 库，导致彼此的结论全废）。
- Bash 只用于只读查看：grep / find / cat / wc / git diff / git status / 用 .venv 直接调纯解析函数或内存 SQLite（不许碰 testplatform_test）。
- 优先 Read / Grep / Glob 精确定位，再读源码；不要在没读代码前猜。`

const COMMON = `你在审查一个已完成的测试开发平台（FastAPI + SQLAlchemy 2.0 + Alembic + React18/TS5.6/Vite/antd5/react-query5）里新建的「接口管理 / API Catalog」模块。仓库根目录：${ROOT}

铁律：
- ${TOOLING}
- 只报**真缺陷**：必须给出「具体输入 -> 具体错误输出」的确定性失败路径。不报风格、命名、注释、「这样更好」的建议。
- 宁可少报不要误报。没有真缺陷就返回空 findings 数组。
- 已接受的设计约束（**不要报**）：本阶段明确不做 AI/LangGraph/Mock/安全测试/性能测试；feature-local 表不进 app/models/__init__.py 是刻意的；数据库不设 CHECK 约束是既有约定；service owns commit、router 不提交是既有约定；越权/不可见项目按 404 隐藏存在性是既定设计；调试仅平台管理员是既定设计。
- 已确认并已修/待修的既有结论（**不要重复报**）：
  - api_service.py:624 create_relation 函数体用了未定义变量 user（参数名是 actor）-> NameError 500
  - api_service.py:275 create_module 不拒绝保留名「未分类」-> ensure_default_module 唯一约束冲突 500
  - openapi_parser.py:467 _parse_status_code 把 default/2XX 映射成 0 -> confirm 阶段 ApiResponseIn(ge=100,le=599) ValidationError 500
  - openapi_parser.py:376 OpenAPI 3.1 的 type 数组型塞进 InternalParameter.type -> pydantic 失败
  - curl_parser.py:353 Cookie 参数真实值写进 example（脱敏失效）
  - curl_parser.py:36 X-Token / X-Access-Token 不在 _SENSITIVE_HEADERS -> 明文落库
  - curl_parser.py:270 带 -d 无 -X 按 GET 入库；curl_parser.py:101 内联短选项 -XPOST/-d= 丢失
  - debug_service.py:74 urlsplit().port 的 ValueError 在 try 外、在白名单校验之前 -> 500
  - import_service.py:187 confirm 丢弃 user_module_id/tag_to_module_map；:307 body diff 过窄；:135 confirm TOCTOU
  - api_service.py:429 ApiInterfaceCreate.path 无 normalize_path；:782 _diff_* 忽略 description/example 等字段
  - tests 硬编码 head == "0004"；README 停留在阶段一
- 用中文写结论。

你的任务：`

const BIZ_COMMON = `你在审查同一个仓库里「业务场景 / Business」模块的**未提交阶段二改动**（业务执行引擎）。仓库根：${ROOT}，分支 feature/business-executor，工作树脏：16 文件已修改 + 5 处新增，全部**未提交、未验证、从未跑过测试**。

铁律：
- ${TOOLING}
- 只报**真缺陷**：具体输入 -> 具体错误输出。不报风格/命名/注释建议。宁可少报不要误报。
- 已接受设计约束（不报）：本阶段不做 AI/LangGraph/Mock/安全/性能测试；feature-local 表不进 app/models/__init__.py；DB 不设 CHECK；service owns commit、router 不提交；越权/不可见按 404 隐藏存在性；调试仅平台管理员。
- 已知：backend 全量 pytest 93 例在上次通过，**但那批改动当时还不存在**，所以 test_11_business_executor.py 从未被执行过；已入库迁移链 head 是 0004，0005_business_phase2.py 是新增未入库；tests 里现有断言写的是 head == 0004（这一条已另行确认，不必重复报，但要检查 0005 本身的正确性）。
- 建议先跑 git diff --stat 与 git diff -- backend/app/features/business 看清改动范围，再逐个读新增文件与 0005 迁移。
- 用中文写结论。

你的任务：`

// 上轮 4 个从未运行的维度（429 导致 agent 直接死掉）。串行跑，不再并发爆发。
const DIMENSIONS = [
  {
    key: 'api-service',
    common: COMMON,
    prompt: `审查 CRUD 服务：${ROOT}/backend/app/features/api_catalog/services/api_service.py 与 router.py。
重点：两级模块限制在所有路径（create / move / 删除后孤儿 parent / 把模块移到自己子树形成环）；未分类默认模块在 update_module 里改非 name 字段是否绕过保护；delete_module 把子接口归未分类时用的是 SET NULL 还是显式 UPDATE，跨事务是否一致；delete_interface 级联是否覆盖 api_relation 的 source/target（两边都有 FK 到 interface，删 A 时指向 A 的 relation 是否真的删干净）；list_interfaces 的 keyword/method/module_id/status 过滤是否 case 一致、status 是否校验合法值、分页是否正确、是否越权读到别的项目；move_interface / move_module 的 project 归属校验；N+1 查询（详情里 parameters/responses 是否逐条查）；save_request / save_responses 整体替换与 change_log / source_hash 的一致性；delete_relation 的权限与归属校验。`,
  },
  {
    key: 'contract',
    common: COMMON,
    prompt: `前后端契约逐端点对齐审查。对照 ${ROOT}/backend/app/features/api_catalog/router.py 的全部端点与 schemas.py 的 response_model，以及 ${ROOT}/frontend/src/api/apiCatalog.ts 的方法、${ROOT}/frontend/src/types/index.ts 的 Api* 类型、页面调用点。
重点：**逐端点**核对——路径与 HTTP 方法是否一致；请求体字段名（snake_case）与前端 type 是否逐字段一致且必填/可选一致；response_model 的字段名与前端解析字段是否一致（特别注意后端返回 dict 还是 model、字段是否被 alias）；分页信封结构（backend 的 Paginated/ApiItemListResponse/ApiInterfaceListResponse/ApiChangeLogListResponse/ApiImportRecordListResponse 到底长什么样：items/total 还是别的键，前端 PaginationState 用的 page/page_size 是否与后端 Query 参数一致）；listModules 返回纯数组 vs 分页；listRelations 返回 items+total 但前端当成 items 用；ApiRequestBundleResponse / ApiResponsesBundleResponse 的嵌套结构（parameters/body/responses 键名）是否与前端 tab 取值一致；枚举取值集合（ApiStatus/ApiSourceType/ParamLocation/BodyType/RelationType/ChangeType/ImportClassification）是否与后端常量完全一致、有没有前端多一个或少一个导致 Select 崩；日期格式字符串；None -> null 的可选处理；前端传的 status 过滤值是字符串枚举还是中文标签（**重点检查 ModuleTree 里 status as never 那处到底传了什么**）。`,
  },
  {
    key: 'migration-orm',
    common: COMMON,
    prompt: `迁移与 ORM 一致性审查：${ROOT}/backend/alembic/versions/0003_create_api_catalog_tables.py 与 0004（business 建表）对比模型文件 ${ROOT}/backend/app/features/api_catalog/models/*.py 与 ${ROOT}/backend/app/features/business/models/*.py。
重点：逐列比对每张表——列名、类型长度（String(n) 是否一致）、nullable、server_default（ORM default/server_default 与 sa.server_default 是否一致）、外键 ondelete（CASCADE / SET NULL 是否逐条对上）、UniqueConstraint 名称与列顺序、Index 名称与列；ORM 的 index=True 是否与 __table_args__ 里的显式 Index 重名（**这个坑在 api_interface.source_hash 上真实发生过，会报 DuplicateTable，请检查其余模型有没有同类问题**）；_INDEX_DEFINITIONS 与 ORM 实际生成的索引名是否一一对应（漏建或多余）；表注释是否一致；upgrade 的幂等（existing_indexes 用的 inspector 是否在循环里失效——注意 existing_indexes 只在表存在性检查后取一次，而表列表用了一个更早的 inspector 快照，重放时的行为）；downgrade 是否漏删唯一约束索引、删表顺序是否违反 FK 依赖；head/down_revision 链；0004 依赖 0003 的表是否存在。`,
  },
  {
    key: 'business-phase2',
    common: BIZ_COMMON,
    prompt: `审查这批未提交的阶段二改动本身。先看范围：git diff --stat，然后 git diff 看已修改的文件，再读新增文件。
重点：
- 0005 迁移与 ORM 模型逐列对齐（business_action / business_binding / business_flow / business_variable_ref 的改动 + 新增 execution 表）：新增列有没有 server_default 或导致 NOT NULL 无默认值、nullable 与 ORM 是否一致、有没有 index=True 与 __table_args__ 显式 Index 重名（**这个坑在 api_interface 上真实发生过，会报 DuplicateTable**）、down_revision 是否接 0004、幂等保护（inspect 检查表存在、IF NOT EXISTS）、downgrade 是否完整。
- 执行引擎：executors/ 目录与 services/execution_service.py。变量引用（variable_ref）的解析与替换是否能取到别的接口/别的执行的值、是否越权读别的项目的数据；执行顺序与失败传播（前置步骤失败后是否还继续执行后续步骤）；超时/重试；事务边界（一次执行中途失败会不会留下半成品 execution 记录、状态是否卡在 RUNNING）；execution 记录的 project_id 隔离；并发两次执行同一 flow 会不会产生冲突或脏数据；长执行是否阻塞；结果大小是否截断。
- 权限：新增 router 端点是否都校验了 viewer+ 读 / member+ 写 / 平台管理员执行；路径是否与既有端点冲突。
- 前后端契约：business.ts 与 types/index.ts 的新字段、ActionDrawer / FlowDetail / RulePanel 的调用是否与后端 schema 逐字段一致（必填/可选、枚举值、分页信封）。
- 前端：新组件的 hooks 顺序（条件 return 前的 hooks）、react-query key、antd5 API 误用、空态/错误态。
- 有没有把敏感值 / 凭据落库；有没有把不该进 app/models/__init__.py 的 feature-local 表加进去。`,
  },
]

// 上轮 verify agent 429 死亡、结论被丢弃的 6 条（findings 本体完整，只是缺裁定）。
const DROPPED = [
  {
    dimension: 'rerun-debug-ssrf',
    file: 'backend/app/features/api_catalog/services/debug_service.py',
    line: 162,
    severity: 'medium',
    title: 'json 分支兜底返回 {"headers": {}} 与调用点的 headers= 关键字冲突，调试必然抛 TypeError -> 500',
    failure_scenario: "接口保存 body_type='json' 且 raw_text 为非法 JSON（ApiBodyIn.raw_text 只是 str|None，无 JSON 合法性校验，_replace_body 原样落库；用户在前端手输 {name 即成立），随后管理员正常调用 POST /apis/{id}/debug（override_body 省略）。流程走到 _build_send_kwargs：raw 非空 -> json.loads(raw) 抛 ValueError -> 命中 return {\"content\": raw, \"headers\": {}}（第162行）；而第119行是 client.request(method, url, headers=headers, params=query, **send_kwargs)，headers 在 httpx 0.28.1 的 Client.request 签名里是关键字参数 -> 实际输出 TypeError: httpx._client.Client.request() got multiple values for keyword argument 'headers'。该 TypeError 在 try 块内但 except 只捕 httpx.ConnectError / httpx.TimeoutException / httpx.HTTPError / ImportError，全部不匹配 -> 未被吞掉，直接 500 + 堆栈回显。即：任何 JSON 体接口的调试只要 raw 体不是合法 JSON 就永远 500，永远无法发送。",
    fix: '删掉第162行返回值里的 "headers": {}（改为 return {"content": raw}）；更稳妥的做法是 _build_send_kwargs 永不返回 headers 键，把 body_type/content_type 需要设置的头并入调用点的 headers dict 后再一次性传入。顺带把 json.loads 失败从静默降级为 bad_request，避免把坏 JSON 当 text 原样发出去。',
  },
  {
    dimension: 'rerun-debug-ssrf',
    file: 'backend/app/features/api_catalog/services/debug_service.py',
    line: 131,
    severity: 'medium',
    title: '_MAX_RESPONSE_BODY 截断发生在全量读入之后，不限制内存；且超时按阶段而非总时限，可被慢速/超大响应拖死 worker',
    failure_scenario: '第32-33行的注释声称 _MAX_RESPONSE_BODY=200_000 是"避免超大响应撑爆"的上限，但第131行用的是 resp.text：httpx 的 Client.send 在 stream=False 时返回前就调用了 response.read() 全量落内存，resp.text 随后再做一次 UTF-8 解码拷贝。所以目标返回 200MB 时，进程先分配 200MB+解码副本，然后才截到 200KB —— 截断完全没起到保护作用，只是控制返回给前端的长度。同时 httpx.Client(timeout=body.timeout) 传标量 = connect/write/read/pool 各得一份（timeout 上限 120s），没有总时限；read 超时是"每次 socket 读"级别，目标每 1 秒吐 1 字节即可让连接无限期存活、内存无限增长。一次平台管理员的正常调试（对白名单内目标发 GET）就能把该 uvicorn worker 打挂，影响所有在线用户。',
    fix: '改用流式并边读边限：with client.stream(method, url, headers=headers, params=query, **send_kwargs) as resp: 内用 resp.iter_bytes() 累积，超过 _MAX_RESPONSE_BODY+1 字节即截断停止读取，然后 status_code = resp.status_code、resp.headers 直接取（流式下头已可读）。另把 timeout 显式写成 httpx.Timeout(connect=..., write=..., read=...) 并把 body.timeout 当作总预算（或用外层 deadline 包一层），避免 4 倍放大与慢速滴流。',
  },
  {
    dimension: 'rerun-import-service',
    file: 'backend/app/features/api_catalog/services/import_service.py',
    line: 93,
    severity: 'low',
    title: '同批导入内 resolve_dry 看不到本批新建的模块，preview 的「推荐模块」与 confirm 实际落库模块不一致',
    failure_scenario: 'preview 走 ModuleResolver.resolve_dry（module_resolver.py:176-237），刻意不创建任何模块；confirm 走 resolve（:119-165），会 find_or_create。具体输入：一个 OpenAPI 文件，/orders/list 带 tags=["订单"]，/orders/detail 不带 tags（已实跑确认两者的 suggested_module 都是 orders，而 /orders/list 的 tag 是「订单」）。preview 输出：/orders/list 推荐模块「订单」（proposed_module_id=null，将新建）、/orders/detail 推荐模块「orders」（走 step 5 URL 推断，因为 step 4 查不到任何已存 iface）。confirm 实际：先建「订单」模块并让 /orders/list 归属它，随后 /orders/detail 在 step 4 用 path LIKE 命中刚 flush 的那条接口，直接复用「订单」。所以预览表上印着「推荐模块 orders」的那行，确认后被放进「订单」，同时「orders」这个模块根本没被创建。分类不受影响（两条都 NEW），但用户按预览预期去树上找 orders 找不到。',
    fix: 'resolve_dry 在预览循环内维护一个批内 module_name->新建模块名 的映射（或先算一遍批内将要创建的模块名），让 step 4/step 5 的判定与 confirm 一致；或在 ImportPreviewItem 的 warnings 里明确提示「同批其他接口可能新建模块并改变本行归属」。',
  },
  {
    dimension: 'rerun-import-service',
    file: 'backend/app/features/api_catalog/services/import_service.py',
    line: 113,
    severity: 'low',
    title: 'preview 响应 existing_count 恒为 0，前端直接展示成「已存在 0」',
    failure_scenario: "preview 的分类只会是 NEW / CHANGED / UNCHANGED（78-92 行，counts 也只建了这三个键，ImportClassification 里的 EXISTING 从未被赋值），第 113 行硬编码 existing_count=0。而前端 ImportPreview.tsx:66 就是 <Tag>已存在 {preview.existing_count}</Tag>，types/index.ts:626 的注释也写着「已存在数」。具体输入：项目里已有 3 条接口被改过、2 条未变、导入 5 条的 OpenAPI。preview 返回 new_count=2、changed_count=3、unchanged_count=2、existing_count=0。界面显示「新增 2 / 有变更 3 / 已存在 0 / 无变化 2 / 共 5 条」—— 用户能看到 3 条明确已被标记为 CHANGED（即库里存在），却同时看到「已存在 0」，且 total 与各分项无法对上已存在的 3 条。",
    fix: "把 existing_count 定为 counts['CHANGED'] + counts['UNCHANGED']（或明确语义为 CHANGED），与前端「已存在」文案对齐；若语义本就不需要该字段，应从 ImportPreviewResponse 和前端标签里一并移除。",
  },
  {
    dimension: 'rerun-parsers',
    file: 'backend/app/features/api_catalog/parsers/curl_parser.py',
    line: 353,
    severity: 'high',
    title: 'Cookie 参数把真实值写进 example，脱敏标记只落在不生效的 schema_json 上，违反本模块「Cookie 不落库真实值」的契约',
    failure_scenario: "parse_curl('curl -b \"sessionid=sess_abc123; sid=xyz456\" https://api.example.com/login') 实测产出参数 [('sessionid','COOKIE','sess_abc123',{'sensitive':True}), ('sid','COOKIE','xyz456',{'sensitive':True})]；parse_curl('curl -H \"Cookie: JSESSIONID=abc; csrf=def\" ...') 同样把 'abc'/'def' 原样写进 example。真实会话值经 ApiParameterIn.example -> api_parameter.example（Text 列）落库，get_interface 详情原样回给项目内任意成员。对比 HEADER 分支：Authorization 写的是占位串 Bearer ${token} 而非真值 —— cookie 分支完全没走 _masked_header_param。更关键的是 schema_json={\"sensitive\": True} 这个标记在整个仓库（后端与前端 src）没有任何一处消费（grep sensitive 只命中 curl_parser 自己与 business/executors/sensitive.py），所以它既不触发 UI 隐藏也不触发服务层屏蔽，纯属装饰。模块 docstring 第 8-10 行明确写着「Cookie/Set-Cookie …… 转成变量占位（如 Bearer ${token}、${cookie}）…… 使导入预览/确认均不落库真实凭证」，且 _masked_header_param 里为 cookie/set-cookie 写了 ${cookie} 分支，但因为 cookie 属于 _CONSUMED_HEADERS，该分支对 Cookie 参数是死代码。",
    fix: 'cookie 分支复用脱敏路径：example 写成 ${cookie}（或按会话变量 ${sessionid}），保留 schema_json={\"sensitive\": True}；非会话 cookie 也应走同一占位而非原值。最小改动即把第 353 行的 example=value 换成占位串，让 _masked_header_param 的 cookie 分支真正被使用。',
  },
  {
    dimension: 'rerun-config-tests',
    file: 'backend/tests/conftest.py',
    line: 31,
    severity: 'low',
    title: '测试库名固定为 testplatform_test，并发 pytest 会话互相 DROP 数据库',
    failure_scenario: "TEST_DATABASE_NAME 默认固定 testplatform_test，test_database（session 作用域）在会话开头 _terminate_connections()（SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname=... AND pid <> pg_backend_pid()）+ DROP DATABASE + CREATE DATABASE，且没有最终 teardown。具体输入->输出：两个 pytest 进程同时跑（例如本地一份 + CI 一份，或两个人各起一份），后启动的进程执行 DROP DATABASE \"testplatform_test\" 并 terminate 掉前者所有连接 -> 前者批量报 psycopg.OperationalError: connection already closed / database \"testplatform_test\" does not exist，两边结论全废，而且失败信息看起来像产品缺陷，很容易被误判。",
    fix: '库名加进程级唯一后缀（如 TEST_DATABASE_NAME-p{os.getpid()}），test_database teardown 里 DROP 掉自己的库；_terminate_connections / test_07 的 _prepare 复用同一份库名派生逻辑。',
  },
]

const verifyPrompt = (f) => `对抗性验证一条代码审查结论。你的默认立场是**推翻它**。

结论（JSON）：
${JSON.stringify(f, null, 2)}

步骤：
1. 读结论指向的文件与相关调用方（仓库根 ${ROOT}）。
2. 尝试构造反例或证明它其实不是缺陷（也许已有校验兜底、也许上游永远给不出这个输入、也许设计约定如此、也许测试已覆盖）。
3. 只有当你能给出「具体输入 -> 具体错误输出」的确定性失败路径时才判 real=true，并复述该路径。

${TOOLING}
已接受的设计约束（据此判 real=false）：本阶段不做 AI/Mock/安全测试/性能测试；feature-local 表不进 app/models/__init__.py；DB 不设 CHECK；service owns commit、router 不提交；越权按 404 隐藏存在性；调试仅平台管理员。
severity 请按真实影响重判，不要照抄。用中文写 reasoning。`

phase('FindMissing')
const collected = []
for (const d of DIMENSIONS) {
  const r = await agent(d.common + d.prompt, {
    label: 'find:' + d.key,
    phase: 'FindMissing',
    schema: FINDINGS_SCHEMA,
    effort: 'high',
  })
  if (!r || !r.findings || r.findings.length === 0) {
    log(d.key + ': 无发现或 agent 失败')
    continue
  }
  log(d.key + ': ' + r.findings.length + ' 条待验证')
  for (const f of r.findings) collected.push({ f, dim: d.key, origin: 'new' })
}

phase('Verify')
const tasks = collected.concat(DROPPED.map((f) => ({ f, dim: f.dimension, origin: 'rerun' })))
log('待验证总数 ' + tasks.length + '（新 ' + collected.length + ' + 重审 ' + DROPPED.length + '）')

const out = await parallel(
  tasks.map((t, i) => () =>
    agent(verifyPrompt(t.f), {
      label: 'verify:' + ((t.f.file || t.dim).split('/').pop() + ':' + (t.f.line || i)),
      phase: 'Verify',
      schema: VERDICT_SCHEMA,
      effort: 'high',
    })
      .then((v) => ({ ...t.f, dimension: t.dim, origin: t.origin, verdict: v }))
  )
)

const all = out.filter(Boolean)
const dropped = all.filter((t) => !t.verdict)
const confirmed = all.filter((t) => t.verdict && t.verdict.real)
const refuted = all.filter((t) => t.verdict && !t.verdict.real)
log('裁定：' + confirmed.length + ' 成立 / ' + refuted.length + ' 推翻 / ' + dropped.length + ' 再次失败需人工复核')

const severityOf = (f) => f.verdict?.severity || f.severity
const bySeverity = (sev) => confirmed.filter((f) => severityOf(f) === sev)

return {
  new_findings_from_blind_dimensions: collected.length,
  reverified_dropped: DROPPED.length,
  verified_ok: confirmed.length,
  refuted: refuted.length,
  still_unverified: dropped.length,
  counts: {
    critical: bySeverity('critical').length,
    high: bySeverity('high').length,
    medium: bySeverity('medium').length,
    low: bySeverity('low').length,
  },
  confirmed: confirmed
    .slice()
    .sort((a, b) => {
      const order = { critical: 0, high: 1, medium: 2, low: 3 }
      return (order[severityOf(a)] ?? 9) - (order[severityOf(b)] ?? 9)
    })
    .map((f) => ({
      origin: f.origin,
      dimension: f.dimension,
      file: f.file,
      line: f.line,
      severity: severityOf(f),
      title: f.title,
      failure_scenario: f.failure_scenario,
      fix: f.verdict.fix || f.fix,
      reasoning: f.verdict.reasoning,
    })),
  refuted_titles: refuted.map((f) => ({
    origin: f.origin,
    file: f.file,
    title: f.title,
    why: f.verdict.reasoning,
  })),
  still_unverified: dropped.map((f) => ({
    file: f.file,
    line: f.line,
    title: f.title,
  })),
}
