export const meta = {
  name: 'api-catalog-exhaustive-review',
  description: '穷尽审查：API Catalog 9 维度 + 业务阶段二未提交改动 1 维度，每条结论对抗性反证，最后完整性补漏',
  phases: [
    { title: 'Find', detail: '10 个维度独立评审（导入/CRUD/解析器/权限/调试SSRF/迁移ORM/前端TS/契约/配置测试/业务阶段二）' },
    { title: 'Verify', detail: '对抗性反证每条结论' },
    { title: 'Sweep', detail: '完整性批评者找漏网之鱼' },
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
- Bash 只用于只读查看：grep / find / cat / wc / git diff / git status。
- 优先 Read / Grep / Glob 精确定位，再读源码；不要在没读代码前猜。`

const COMMON = `你在审查一个已完成的测试开发平台（FastAPI + SQLAlchemy 2.0 + Alembic + React18/TS5.6/Vite/antd5/react-query5）里新建的「接口管理 / API Catalog」模块。仓库根目录：${ROOT}

铁律：
- ${TOOLING}
- 只报**真缺陷**：必须给出「具体输入 -> 具体错误输出」的确定性失败路径。不报风格、命名、注释、「这样更好」的建议。
- 宁可少报不要误报。没有真缺陷就返回空 findings 数组。
- 已接受的设计约束（**不要报**）：本阶段明确不做 AI/LangGraph/Mock/安全测试/性能测试；feature-local 表不进 app/models/__init__.py 是刻意的；数据库不设 CHECK 约束是既有约定；service owns commit、router 不提交是既有约定；越权/不可见项目按 404 隐藏存在性是既定设计；调试仅平台管理员是既定设计。
- 已知事实（不要重复报）：后端 pytest 全量 93 例通过（含 Curl 脱敏、OpenAPI JSON/YAML/Swagger 解析、预览->确认幂等、变更检测写 change_log、调试白名单 403/放行、viewer 403/越权 404）；前端 npm run typecheck 与 npm run build 均已零错误通过；已入库迁移链 head = 0004；api_interface.source_hash 的重复索引冲突已修掉。
- 工作树状态（**不是你的审查重点**）：business 模块有约 16 个已修改文件 + 5 处新增（0005 迁移、executors/、execution.py、execution_service.py、test_11_business_executor.py），是另一批未提交改动，另有独立维度负责，别当缺陷报。
- 用中文写结论。

你的任务：`

const BIZ_COMMON = `你在审查同一个仓库里「业务场景 / Business」模块的**未提交阶段二改动**（业务执行引擎）。仓库根：${ROOT}，分支 feature/business-executor，工作树脏：16 文件已修改 + 5 处新增，全部**未提交、未验证、从未跑过测试**。

铁律：
- ${TOOLING}
- 只报**真缺陷**：具体输入 -> 具体错误输出。不报风格/命名/注释建议。宁可少报不要误报。
- 已接受设计约束（不报）：本阶段不做 AI/LangGraph/Mock/安全/性能测试；feature-local 表不进 app/models/__init__.py；DB 不设 CHECK；service owns commit、router 不提交；越权/不可见按 404 隐藏存在性；调试仅平台管理员。
- 已知：backend 全量 pytest 93 例在上次通过，**但那批改动当时还不存在**，所以 test_11_business_executor.py 从未被执行过；已入库迁移链 head 是 0004，0005_business_phase2.py 是新增未入库；tests 里现有断言写的是 head == 0004。
- 建议先跑 git diff --stat 与 git diff -- backend/app/features/business 看清改动范围，再逐个读新增文件与 0005 迁移。
- 用中文写结论。

你的任务：`

const DIMENSIONS = [
  {
    key: 'import-service',
    common: COMMON,
    prompt: `审查导入链路：${ROOT}/backend/app/features/api_catalog/services/import_service.py、hash.py、schemas.py、router.py 的 preview/confirm 端点。
重点：preview 与 confirm 是否可能给出不同分类（时间/顺序不一致、preview 用一次 hash、confirm 重算不一致）；source_hash 规范化是否稳定（字段排序、None vs 缺省、数字 1 vs 1.0、dict 顺序、浮点、空数组）；同一次导入里两条 path 相同但顺序不同是否互相覆盖；confirm 是否真正单事务（部分失败会不会留半条）；selected_items 越界/重复/负数索引；user_module_id 不属于该项目时；UNCHANGED 计入 skipped 是否与 import_record 计数一致；并发两次 confirm 是否产生重复行（唯一约束兜底了吗）；change_log 的 diff_json 粒度是否正确、module_changed 有没有漏写；import_record 的 source_hash 聚合是否合理。`,
  },
  {
    key: 'api-service',
    common: COMMON,
    prompt: `审查 CRUD 服务：${ROOT}/backend/app/features/api_catalog/services/api_service.py 与 router.py。
重点：两级模块限制在所有路径（create / move / 删除后孤儿 parent / 把模块移到自己子树形成环）；未分类默认模块在 update_module 里改非 name 字段是否绕过保护；delete_module 把子接口归未分类时用的是 SET NULL 还是显式 UPDATE，跨事务是否一致；delete_interface 级联是否覆盖 api_relation 的 source/target（两边都有 FK 到 interface，删 A 时指向 A 的 relation 是否真的删干净）；list_interfaces 的 keyword/method/module_id/status 过滤是否 case 一致、status 是否校验合法值、分页是否正确、是否越权读到别的项目；move_interface / move_module 的 project 归属校验；N+1 查询（详情里 parameters/responses 是否逐条查）。`,
  },
  {
    key: 'parsers',
    common: COMMON,
    prompt: `审查解析器：${ROOT}/backend/app/features/api_catalog/parsers/curl_parser.py 与 openapi_parser.py。
Curl 重点：敏感头覆盖面（Authorization/Token/Cookie/Set-Cookie/X-Api-Key/X-Token/api-key/Basic/base64 用户:密码/-u/--user/-b/--cookie/--header 的大小写变体）；脱敏后是否**完全不落库真实值**（例如 Basic 凭据转成 \${token} 时原值是否仍残留在别处）；URL 里带 query 的 path 是否被误并入 path；path 模板 {id} 与已解析 query 的重复；-d 多次出现是否覆盖；--data-urlencode / -F 表单字段；引号与转义；无 URL 或非法 URL 的报错；method 未指定时 -d 是否默认 POST；相对 URL 处理。
OpenAPI 重点：YAML 用 safe_load 是否真的（有无 load()）；顶层既不是 openapi 也不是 swagger 时；openapi 3.0 requestBody 非 application/json 时；3.1 nullable/type 数组；$ref 解析（#/components/schemas 与 definitions 跨文件 $ref）；parameters 里的 $ref；required 缺失默认；response code 是 '200' / 200 / 'default' / 'X' 的处理；重复 path+method；summary 缺失时 name 回退；tags 空数组。`,
  },
  {
    key: 'authz',
    common: COMMON,
    prompt: `审查权限：${ROOT}/backend/app/features/api_catalog/router.py 与 services/api_service.py、import_service.py、debug_service.py 里的可见性判断。
重点：每个端点的读 viewer+ / 写 member+ / 调试 platform admin 是否都真的在校验（逐端点核对）；不可见项目 -> 404 隐藏存在性是否在**所有**读端点一致实现（含 /apis/{id}/relations、/api-relations/{id}、/history、import-records、/request、/responses、/move、module 端点）；viewer 能否通过写端点绕过（例如 PATCH /api-modules 未校验）；admin 是否被当成全项目可见而绕过项目边界；import preview 与 confirm 是否都要求 member+；confirm 里 user_module_id 指向别的项目模块时是否越权；跨项目 relation 是否禁止；删除类端点是否校验项目；错误信息是否泄露存在性（403 vs 404 混用）。`,
  },
  {
    key: 'debug-ssrf',
    common: COMMON,
    prompt: `安全审查调试执行器：${ROOT}/backend/app/features/api_catalog/services/debug_service.py（以及它调用的环境模型 app/models/configuration.py、app/models/project.py 的 ProjectOutboundTarget）。
这是本模块最需要严打的一面。重点：
- 白名单是否可绕过：scheme/host/port 解析（默认端口 80/443 是否补全后再比对）、端口不写时；host 大小写 / 末尾点 / 国际域名 IDNA；IPv6 / IPv6 带端口写法；IPv4 十进制/八进制/带前导零写法；127.0.0.1 vs localhost vs 0.0.0.0；URL 带 userinfo（http://host@realhost）；fragment；percent-encoding；大小写 scheme。
- **重定向**：httpx 默认 follow_redirects=False？如果是 True 或没显式关闭，白名单可被 302 跳到任意内网地址绕过。必须显式关闭并确认。
- DNS rebinding：解析后与连接时的 host 是否可能不一致；白名单按 host 还是按解析后 IP 比对。
- 是否限制只能访问 outbound_target 的 (scheme,host,port)，还是只看项目下存在该记录（enabled=False 是否被忽略、is_production 是否被忽略、project_id 是否真的过滤）。
- 凭据/敏感信息：响应是否可能带 Set-Cookie 或回显请求体里的 token；返回给前端的 request_url 是否含 query/body 里的敏感值；日志是否打印。
- 响应保护：response_body 截断上限、超时是否真的生效（connect+read 各自超时）、timeout 上下界、超大 body 是否内存爆；httpx client 是否关闭（连接泄漏）；同步 client 在线程池里是否阻塞。
- 拼装：path 参数替换 {id} 时的 URL 编码；未提供的 path 参数导致 404 还是拼接错误；query 合并顺序；headers 优先级（environment.default_headers < 接口 HEADER 参数 < override）；override_body 与 body_type 不一致时的行为；Content-Type 处理；form/multipart 组装。
- 仅平台管理员：require_platform_admin 是否覆盖。
任何一点能绕过白名单访问任意地址都是 critical。`,
  },
  {
    key: 'migration-orm',
    common: COMMON,
    prompt: `迁移与 ORM 一致性审查：${ROOT}/backend/alembic/versions/0003_create_api_catalog_tables.py 对比 8 个模型文件 ${ROOT}/backend/app/features/api_catalog/models/*.py。
重点：逐列比对 8 张表——列名、类型长度（String(n) 是否一致）、nullable、server_default（ORM default/server_default 与 sa.server_default 是否一致）、外键 ondelete（CASCADE / SET NULL 是否逐条对上）、UniqueConstraint 名称与列顺序、Index 名称与列；ORM 的 index=True 是否与 __table_args__ 里的显式 Index 重名（**已知 source_hash 那个坑已经修掉，请检查其余 7 个模型有没有同类问题**）；_INDEX_DEFINITIONS 与 ORM 实际生成的索引名是否一一对应（漏建或多余）；表注释是否一致；upgrade 的幂等（existing_indexes 用的 inspector 是否在循环里失效——注意 existing_indexes 只在表存在性检查后取一次，而表列表用了一个更早的 inspector 快照，重放时的行为）；downgrade 是否漏删唯一约束索引、删表顺序是否违反 FK 依赖；head/down_revision 链；0004 依赖 0003 的表是否存在；_TABLES_IN_ORDER 与 _INDEX_DEFINITIONS 的键是否一致。`,
  },
  {
    key: 'frontend-ts',
    common: COMMON,
    prompt: `前端运行期行为审查（api_catalog 页面）。tsconfig 开启 strict + noUnusedLocals + noUnusedParameters + noUncheckedSideEffectImports + isolatedModules + noFallthroughCasesInSwitch，见 ${ROOT}/frontend/tsconfig.app.json。
范围：${ROOT}/frontend/src/pages/console/ApiCatalog/ 全部文件、${ROOT}/frontend/src/api/apiCatalog.ts、${ROOT}/frontend/src/types/index.ts 的 Api* 部分。
**前端已通过 npm run typecheck 与 npm run build（零错误），类型层面不用查了**，重点转向运行期行为：
- antd 5 API 运行期误用：Tabs items、Tree treeData 与 showLine/blockNode、Segmented options/onChange、Descriptions、Modal/Drawer confirmLoading 与 open、InputNumber onChange 的 null、Table columns 的 render 签名与 dataIndex、Checkbox checked、Tag color 传 undefined、Form.Item 泛型、Input.Search value=undefined。
- react-query v5 运行期：queryFn 在 enabled=false 时 apiId 断言；isPending/isError 分支后 query.data 是否可能 undefined 却被解构；useQuery 返回 data undefined 时的 ?. 使用；invalidateQueries 前缀是否与约定一致。
- 运行时 bug：JsonView 对非 JSON 对象（数组、null、循环引用 JSON.stringify 抛错）；toTreeData 对 Set/Map/undefined/NaN/循环引用；RequestTab/ResponseTab 的 JSON.parse 抛错路径；prefillKv 里 p.example ?? p.default_value 实际值可能是 number 而类型声明 string；ImportPreview 的 selectedForConfirm 逻辑与 defaultSelected 长度比较边界；useMemo 依赖缺项（treeData 依赖里含 renameForm/modal/deleteMutation 是否稳定）；useEffect 依赖 query.data 导致重复 setParams 或死循环；分页 page_size 上限；RelationTab 的 pagination 手写 total 是否与实际 total 不一致导致显示错误；DebugTab 在非管理员时提前 return 但 hooks 已声明（是否违反 rules of hooks）；useAuth().isPlatformAdmin 的可用性。
- 边界态：空项目/空模块/接口无参数无响应时的渲染。`,
  },
  {
    key: 'contract',
    common: COMMON,
    prompt: `前后端契约逐端点对齐审查。对照 ${ROOT}/backend/app/features/api_catalog/router.py 的 21 个端点与 schemas.py 的 response_model，以及 ${ROOT}/frontend/src/api/apiCatalog.ts 的 21 个方法、${ROOT}/frontend/src/types/index.ts 的 Api* 类型、页面调用点。
重点：**逐端点**核对——路径与 HTTP 方法是否一致；请求体字段名（snake_case）与前端 type 是否逐字段一致且必填/可选一致；response_model 的字段名与前端解析字段是否一致（特别注意后端返回 dict 还是 model、字段是否被 alias）；分页信封结构（backend 的 Paginated/ApiItemListResponse/ApiInterfaceListResponse/ApiChangeLogListResponse/ApiImportRecordListResponse 到底长什么样：items/total 还是别的键，前端 PaginationState 用的 page/page_size 是否与后端 Query 参数一致）；listModules 返回纯数组 vs 分页；listRelations 返回 items+total 但前端当成 items 用；ApiRequestBundleResponse / ApiResponsesBundleResponse 的嵌套结构（parameters/body/responses 键名）是否与前端 tab 取值一致；枚举取值集合（ApiStatus/ApiSourceType/ParamLocation/BodyType/RelationType/ChangeType/ImportClassification）是否与后端常量完全一致、有没有前端多一个或少一个导致 Select 崩；日期格式字符串；None -> null 的可选处理；前端传的 status 过滤值是字符串枚举还是中文标签（**重点检查 ModuleTree 里 status as never 那处到底传了什么**）。`,
  },
  {
    key: 'config-tests',
    common: COMMON,
    prompt: `配置、依赖与测试健壮性审查：
- ${ROOT}/backend/requirements.txt：PyYAML/httpx 位置与版本范围是否与代码用法匹配（yaml.safe_load、httpx.Client 同步 API）；是否有代码 import 了 requirements 里没有的包（grep 一遍 api_catalog 下所有 import）。
- ${ROOT}/backend/app/main.py：api_catalog_router 注册位置、prefix、router 之间路径冲突风险（是否与既有 /projects/... 路由、bug 路由撞路径）。
- ${ROOT}/.gitignore 与真实文件：确认 backend/.env（含真实 DB 密码）、.venv/、node_modules/、frontend/dist/、.claude/settings.local.json、tmp*.txt 都被排除；有没有**其他**敏感文件没被排除（grep 整个仓库找 token/secret/password/api_key 字面量，排除 .venv 与 node_modules 与 .git）。
- ${ROOT}/backend/tests/test_api_catalog.py 与 conftest：测试隔离（唯一约束/自增/跨测试状态泄漏）、fixture 作用域、顺序依赖、api fixture 的 session 复用是否导致跨用例认证状态串；有没有测试会因并行/重跑失败；有没有断言太弱（只查 200 不查内容）。
- README / docs 是否需要说明白名单前置条件（这是运行期风险）。`,
  },
  {
    key: 'business-phase2',
    common: BIZ_COMMON,
    prompt: `审查这批未提交的阶段二改动本身。先看范围：git diff --stat，然后 git diff 看已修改的 16 个文件，再读 5 处新增。
重点：
- 0005 迁移与 ORM 模型逐列对齐（business_action / business_binding / business_flow / business_variable_ref 的改动 + 新增 execution 表）：新增列有没有 server_default 或导致 NOT NULL 无默认值、nullable 与 ORM 是否一致、有没有 index=True 与 __table_args__ 显式 Index 重名（**这个坑在 api_interface 上真实发生过，会报 DuplicateTable**）、down_revision 是否接 0004、幂等保护（inspect 检查表存在、IF NOT EXISTS）、downgrade 是否完整。
- **tests 里断言的是 head == 0004，0005 提交后这两处断言必然失败**——确认一下并作为一条 finding 报出。
- 执行引擎：executors/ 目录与 services/execution_service.py。变量引用（variable_ref）的解析与替换是否能取到别的接口/别的执行的值、是否越权读别的项目的数据；执行顺序与失败传播（前置步骤失败后是否还继续执行后续步骤）；超时/重试；事务边界（一次执行中途失败会不会留下半成品 execution 记录、状态是否卡在 RUNNING）；execution 记录的 project_id 隔离；并发两次执行同一 flow 会不会产生冲突或脏数据；长执行是否阻塞；结果大小是否截断。
- 权限：新增 router 端点是否都校验了 viewer+ 读 / member+ 写 / 平台管理员执行；路径是否与既有端点冲突。
- 前后端契约：business.ts 与 types/index.ts 的新字段、ActionDrawer / FlowDetail / RulePanel 的调用是否与后端 schema 逐字段一致（必填/可选、枚举值、分页信封）。
- 前端：新组件的 hooks 顺序（条件 return 前的 hooks）、react-query key、antd5 API 误用、空态/错误态。
- 有没有把敏感值 / 凭据落库；有没有把不该进 app/models/__init__.py 的 feature-local 表加进去。`,
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

phase('Find')
const results = await pipeline(
  DIMENSIONS,
  (d) =>
    agent(d.common + d.prompt, {
      label: `find:${d.key}`,
      phase: 'Find',
      schema: FINDINGS_SCHEMA,
      effort: 'high',
    }),
  (review, d) => {
    if (!review || !review.findings || review.findings.length === 0) {
      log(`${d.key}: 无发现`)
      return []
    }
    log(`${d.key}: ${review.findings.length} 条待验证`)
    return parallel(
      review.findings.map((f) => () =>
        agent(verifyPrompt(f), {
          label: `verify:${(f.file || d.key).split('/').pop()}`,
          phase: 'Verify',
          schema: VERDICT_SCHEMA,
          effort: 'high',
        })
          .then((v) =>
            v
              ? { ...f, dimension: d.key, checked: review.checked, verdict: v }
              : { ...f, dimension: d.key, checked: review.checked, verdict: null }
          )
      )
    )
  }
)

const found = results.flat().filter(Boolean)
const confirmed = found.filter((f) => f.verdict && f.verdict.real)
const refuted = found.filter((f) => f.verdict && !f.verdict.real)

log(`首轮：${found.length} 条候选，${confirmed.length} 条成立，${refuted.length} 条被推翻`)

phase('Sweep')
const known = confirmed.map((f) => `- [${f.dimension}] ${f.file}:${f.line || '?'} ${f.title}`).join('\n')
const SWEEP_SCHEMA = FINDINGS_SCHEMA
const SWEEPS = [
  {
    key: 'sweep-cross-cutting',
    prompt: `下面是已确认的问题清单，以及本模块已经审查过的 10 个维度：导入链路、CRUD 服务、解析器、权限、调试 SSRF、迁移/ORM、前端 TS、前后端契约、配置与测试、业务阶段二。

已确认清单：
${known || '（空）'}

你的任务是**找漏网之鱼**：只报上面维度不太可能覆盖到的东西。例如：并发与事务边界（同一 Session 内 flush 后读未提交数据、expire_on_commit 影响）、跨模块副作用（api_interface 被 business_binding 引用后删接口的后果）、序列化层（Pydantic v2 model_config、jsonable_encoder、datetime 时区、Decimal/JSON 列默认值 {}）、错误信封一致性（api_catalog 的报错是否走 shared.errors 统一结构、状态码是否与既有约定一致）、空项目/空模块边界、性能（模块树 + 接口列表在几百接口时的查询次数）、OpenAPI/Swagger 的边界输入能否让整个 app 崩（未捕获异常导致 500 而非 400）、以及 API Catalog 的 21 个端点在共享路由前缀下与其他 feature 的路径歧义。
仍然只报有确定性失败路径的真缺陷，宁可空手而归。`,
  },
  {
    key: 'sweep-repro-readme',
    prompt: `完整性批评者：从一个新同事第一次部署这个项目、或第一次跑通全部测试的角度审查。
读 ${ROOT}/README.md、${ROOT}/compose.yaml、${ROOT}/backend/.env.example（若存在）、${ROOT}/docs/development.md、${ROOT}/backend/alembic.ini、seed 脚本、${ROOT}/backend/app/features/api_catalog/__init__.py、${ROOT}/docs/coding-conventions.md。
只报**会导致首次部署/首次跑起来失败**或**会让用户在页面上卡死无解**的确定性问题：迁移顺序是否能让空库从零 upgrade 到 head 并建出全部表；seed 是否会重复执行失败；.env 需要的变量是否都有默认值或示例；前端 vite proxy 指向的后端端口是否与 compose/uvicorn 实际端口一致；README 与 docs 是否还写着旧的端点/表数/迁移 head 而误导（文档缺陷算 low）。
同样要求确定性失败路径，不确定的不报。`,
  },
]

const sweepResults = await pipeline(
  SWEEPS,
  (s) =>
    agent(COMMON + s.prompt, {
      label: `sweep:${s.key}`,
      phase: 'Sweep',
      schema: SWEEP_SCHEMA,
      effort: 'high',
    }),
  (review, s) => {
    if (!review || !review.findings || review.findings.length === 0) return []
    log(`${s.key}: ${review.findings.length} 条待验证`)
    return parallel(
      review.findings.map((f) => () =>
        agent(verifyPrompt(f), {
          label: `verify:${(f.file || s.key).split('/').pop()}`,
          phase: 'Verify',
          schema: VERDICT_SCHEMA,
          effort: 'high',
        })
          .then((v) =>
            v
              ? { ...f, dimension: s.key, checked: review.checked, verdict: v }
              : { ...f, dimension: s.key, checked: review.checked, verdict: null }
          )
      )
    )
  }
)

const sweepFound = sweepResults.flat().filter(Boolean)
const sweepConfirmed = sweepFound.filter((f) => f.verdict && f.verdict.real)

const all = [...confirmed, ...sweepConfirmed]
const bySeverity = (sev) => all.filter((f) => (f.verdict?.severity || f.severity) === sev)
const severityOf = (f) => f.verdict?.severity || f.severity

return {
  total_confirmed: all.length,
  counts: {
    critical: bySeverity('critical').length,
    high: bySeverity('high').length,
    medium: bySeverity('medium').length,
    low: bySeverity('low').length,
  },
  first_round_candidates: found.length,
  first_round_refuted: refuted.length,
  sweep_candidates: sweepFound.length,
  refuted_titles: refuted.map((f) => ({
    dimension: f.dimension,
    file: f.file,
    title: f.title,
    why: f.verdict?.reasoning || '',
  })),
  confirmed: all
    .slice()
    .sort((a, b) => {
      const order = { critical: 0, high: 1, medium: 2, low: 3 }
      return (order[severityOf(a)] ?? 9) - (order[severityOf(b)] ?? 9)
    })
    .map((f) => ({
      dimension: f.dimension,
      file: f.file,
      line: f.line,
      severity: severityOf(f),
      title: f.title,
      failure_scenario: f.failure_scenario,
      fix: f.verdict?.fix || f.fix,
      reasoning: f.verdict?.reasoning || '',
    })),
}
