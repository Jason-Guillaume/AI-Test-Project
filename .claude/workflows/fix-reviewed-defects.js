export const meta = {
  name: 'fix-reviewed-defects',
  description: '修复评审确认的缺陷：先对抗性验证 5 条未裁定结论，再按文件分组并行修复。用户正在编辑的文件一律不碰',
  phases: [
    { title: 'Verify', detail: '对抗性验证 5 条未裁定结论（上轮 429 死掉的那批 + 1 条自相矛盾）' },
    { title: 'Fix', detail: '按文件分组并行修复，每组只动自己的文件' },
  ],
}

const ROOT = '/Users/a1/Desktop/ai-test-project'
const VENV = ROOT + '/backend/.venv/bin/python'

// 用户此刻正在编辑器里改这些文件。任何 agent 都不许碰。
const USER_FILES = [
  'backend/tests/test_01_schema_and_seed.py',
  'frontend/src/App.tsx',
  'frontend/src/layouts/ConsoleLayout.tsx',
  'frontend/src/pages/console/BusinessManagement/FlowDetail.tsx',
  'frontend/src/types/index.ts',
  'frontend/src/api/testManagement.ts',
  'frontend/src/pages/console/TestManagement/',
].join('\n  ')

const RULES = [
  '铁律（违反即任务失败）：',
  '- 只修改任务列出的文件。绝不碰其他文件。',
  '- **绝对不要碰这些用户正在编辑的文件**：',
  '  ' + USER_FILES,
  '- 禁止运行 pytest / alembic / npm / pip / tsc（多个 agent 并发跑会互相摧毁 testplatform_test 库；主会话稍后统一跑）。',
  '- 禁止 git add / git commit / git push / git stash / git checkout（主会话统一提交）。只读 git diff 可以。',
  '- 允许只读：Read / Grep / Glob / grep / find / sed -n / ' + VENV + ' -c（纯函数调用或 py_compile 语法检查，不碰数据库）。',
  '- 不重构、不重排无关代码、不「顺手优化」、不加无关 import。只修本缺陷。',
  '- 不加任何新第三方依赖。',
  '- 可选：在对应测试文件末尾追加回归测试（照抄该文件已有夹具用法）。不确定就不要加——主会话跑不了你的中间态，别留下跑不通的测试。**绝不修改已有断言来让代码通过**。',
  '',
  '项目约定（必须遵守）：',
  '- 所有给人看的文字（注释、docstring、错误消息、UI 文案）用中文；标识符 / 库名 / 命令保持英文。',
  '- service 层负责 commit，router 不 commit；跨资源越权统一返 404（不返 403）。',
  '- 错误用 app.shared.errors 的 bad_request / conflict / forbidden / not_found；不要用裸 ValueError / RuntimeError（会被全局 handler 变成 500「服务器内部错误」）。',
  '- feature-local 表不加进 app/models/__init__.py。',
  '- 本仓库真实踩过「ORM index=True 与 __table_args__ 显式 Index 重名 -> DuplicateTable」的坑：改 __table_args__ 前先用 python -c 打印该表的全部索引名确认不重名。',
  '',
  '仓库根目录：' + ROOT,
  '改完后用 sed -n 或 git diff 回看你改的区域，确认改动确实落地且语法正确。',
].join('\n')

const VERDICT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    real: { type: 'boolean' },
    severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
    repro: { type: 'string', description: '确定性复现路径：具体输入 -> 具体错误输出；real=false 时写为什么走不到' },
    reasoning: { type: 'string', description: '中文。逐环说明你读了哪些文件、验证了什么' },
    fix: { type: 'string', description: 'real=true 时给出最小修复（文件+行+具体改法）' },
  },
  required: ['real', 'severity', 'repro', 'reasoning', 'fix'],
}

const FIX_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    files_changed: { type: 'array', items: { type: 'string' }, description: '实际改动的文件（相对仓库根）' },
    summary: { type: 'string', description: '改了什么、为什么这样改、关键代码是什么' },
    verified: { type: 'string', description: '你怎么验证的（读调用方 / grep / python -c 输出）' },
    residual_risk: { type: 'string', description: '残留风险或需主会话确认的点；无则写「无」' },
  },
  required: ['files_changed', 'summary', 'verified', 'residual_risk'],
}

const verifyPrompt = (f) => [
  '对抗性验证一条代码审查结论。你的默认立场是**推翻它**。',
  '',
  '结论：' + f.claim,
  '',
  '步骤：',
  '1. 读结论指向的文件与全部调用方（仓库根 ' + ROOT + '）。',
  '2. 尝试构造反例或证明它不是缺陷：也许上游已经兜住、也许永远给不出这个输入、也许这是既定设计、也许读法本身理解错了。',
  '3. 只有你能给出「具体输入 -> 具体错误输出」的确定性失败路径时才判 real=true，并在 repro 里复述该路径。',
  '',
  f.hints,
  '',
  RULES,
  '（本任务是**只读验证**：不要修改任何文件。）',
  'severity 请按真实影响重判，不要照抄。用中文写 reasoning。',
].join('\n')

const fixPrompt = (t) => [
  '修复一个已确认的代码缺陷。',
  '',
  '要改的文件（**只有这些**）：',
  t.files.join('\n  '),
  '',
  t.detail,
  '',
  RULES,
  '用中文写 summary / verified / residual_risk。',
].join('\n')

// ---------------------------------------------------------------- 5 条待裁定结论
const VERIFY = [
  {
    key: 'ModuleTree',
    label: 'verify:ModuleTree',
    claim: 'frontend/src/pages/console/ApiCatalog/ModuleTree.tsx:63 —— 模块树只拉第一页 200 条接口，项目接口超过 200 个时其余接口在本页永久不可见',
    hints: '读 ModuleTree.tsx 及其调用方（frontend/src/api/apiCatalog.ts 的 listApis、页面容器怎么传参、后端 list_interfaces 的 page/page_size 默认值与 MAX_PAGE_SIZE）。关键问题：listApis 实际传了哪些分页参数？ModuleTree 拿到多少条？树渲染是否有分页 / 懒加载 / 折叠？也许列表端点返回全量（page_size 上限很大），那这条就不成立。',
  },
  {
    key: 'RequestTab',
    label: 'verify:RequestTab',
    claim: 'frontend/src/pages/console/ApiCatalog/tabs/RequestTab.tsx:187 —— 请求体保存时把 json/form/multipart 的 raw_text 一律置 null，静默丢弃示例 body',
    hints: '读 RequestTab.tsx 的保存逻辑，以及后端 PUT /apis/{api_id}/request 的 schema（ApiRequestBundleRequest / ApiBodyIn）与 api_service.save_request 实现。关键问题：前端提交时 raw_text 是否被置 null？后端拿到 null 是真丢数据还是保留旧值？用户在前端有 raw_text 的编辑入口吗——如果他有，置 null 是用户主动清空而非静默丢弃；如果他没有编辑入口却能看到已存的 raw_text，那才成立。',
  },
  {
    key: 'importResolveDry',
    label: 'verify:import-resolve-dry',
    claim: 'backend/app/features/api_catalog/services/import_service.py:93 —— 同批导入内 resolve_dry 看不到本批新建的模块，preview 的「推荐模块」与 confirm 实际落库模块不一致',
    hints: '读 import_service.preview / confirm 与 module_resolver.resolve_dry / resolve。关键问题：preview 每个条目输出什么字段（推荐模块名 / proposed_module_id / warnings）？confirm 会不会真的产出与 preview 展示不同的归属？要给出「哪个接口在预览显示归 A 模块、确认后被放进 B 模块」的具体输入。注意 step 4 的 path LIKE 复用判定：预览时同批接口还没落库、确认时已 flush，这个差异是否真的改变归属。',
  },
  {
    key: 'execution0005indexes',
    label: 'verify:0005-indexes',
    claim: 'backend/alembic/versions/0005_business_phase2.py:120 —— 0005 建 flow_execution / action_execution 时漏建 ORM 声明的 ix_*_id 索引，并额外建了 ORM 未声明的两个复合索引',
    hints: '读 0005 建这两张表的整段，与 backend/app/features/business/models/execution.py 里两个模型的全部 __table_args__ / Index(...) / Column(index=True)。逐条比对：ORM 声明的索引名集合 vs 迁移实际建的索引名集合。关键区分：漏建**纯查询性能索引**（不影响数据正确性）vs 漏建**唯一约束**（影响正确性）——请把两者分开报告，别混成一个结论。结论里若唯一约束没漏，这条的实际影响只是查询性能，severity 应判 low。',
  },
  {
    key: 'execution0005downgrade',
    label: 'verify:0005-downgrade',
    claim: 'backend/alembic/versions/0005_business_phase2.py:230 —— 0005 的 downgrade 删掉 0004 定义的 uq_business_binding_action_type 后从不恢复，反向到 0004 的库与 0004 定义不一致',
    hints: '这条结论此前出现两个**相互矛盾**的裁定：一个判 low 成立，另一个判推翻（理由是失败路径不可复现、且所给 fix 会引入硬失败）。你要独立裁定，不要倾向任何一方。读 0004 与 0005，确认：0004 是否建了 uq_business_binding_action_type；0005 upgrade 是否删了它；0005 downgrade 是否恢复它。然后回答核心问题：这个不一致是否导致可观测的错误输出？如果只在「downgrade 到 0004 之后又做某种操作」时才暴露，给出那条完整路径；找不到可复现的失败路径就判 real=false。另外评估「直接 ADD CONSTRAINT UNIQUE」这个 fix 是否会在已有重复行的库上导致 downgrade 硬失败（阶段二允许多绑定，重复行可能是常态）。',
  },
]

// ---------------------------------------------------------------- 不依赖裁定结果的 8 组修复
const FIX_WAVE1 = [
  {
    key: 'OverviewTab',
    files: ['frontend/src/pages/console/ApiCatalog/tabs/OverviewTab.tsx'],
    detail: [
      '缺陷（severity medium，已对抗性验证成立）：编辑抽屉清空「所属模块」下拉后保存不生效，接口无法移回「未分类」。',
      '',
      '机制：清空下拉得到 module_id = undefined，JSON.stringify 会**丢弃** undefined 键，PATCH 请求体里没有 module_id；后端 body.model_dump(exclude_unset=True) 看不到该字段 -> 直接跳过 -> 返回 200「已保存」但 iface.module_id 不变。重新打开抽屉，下拉仍显示原模块。全页唯一能让接口回到「未分类」的路径就此断掉，且用户没有任何失败提示。',
      '',
      '修法（最小改动）：提交前兜底成显式 null，与同模块新建流程 index.tsx 里 module_id: values.module_id ?? null 的口径一致：',
      '',
      '  const values = await form.validateFields();',
      '  await updateMutation.mutateAsync({',
      '    ...values,',
      '    module_id: values.module_id ?? null,',
      '  });',
      '',
      '注意：',
      '- 不要影响其他字段；确认 module_id 的类型定义允许 null（若前端 DTO 类型是 number 需扩成 number | null，但**不要改 types/index.ts**——那个文件用户在改，若确需改就在 residual_risk 里写明，改成本文件的局部类型断言即可）。',
      '- module_id 未变时后端 value != iface.module_id 为 False，不会误写 MODULE_CHANGED 日志，安全。',
      '- 不要改后端。',
    ].join('\n'),
  },
  {
    key: 'RelationTab',
    files: ['frontend/src/pages/console/ApiCatalog/tabs/RelationTab.tsx'],
    detail: [
      '缺陷（severity medium，已对抗性验证成立）：关联表把「当前接口是 target」的关联也渲染成「目标接口」，且列里显示的是当前接口自己的名字。OUTPUT_INPUT 类型在「提取路径」的语义也因此反向误导。',
      '',
      '先读清楚现状：后端 api_service.list_relations 返回两个方向的行（当前接口是 source_api_id 或 target_api_id 的都返回），以及关联 DTO 到底带哪些字段（source_api_id / target_api_id / source_api_name / target_api_name / relation_type / variable_name / extract_path）。按实际字段名来，不要臆造字段。',
      '',
      '修法（只动这个文件）：',
      '- 在「类型」列附近加一列「方向」：row.source_api_id === apiId ? <Tag>发出</Tag> : <Tag color="purple">被依赖</Tag>',
      '- 「对端接口」列按方向取：out -> row.target_api_name ?? #target_api_id；in -> row.source_api_name ?? #source_api_id。复用现有「目标接口」列的 fallback 写法。',
      '- 「提取路径」列的 tooltip 按方向标注取自哪一侧响应（out 时是 source 侧响应即本接口；in 时是对端响应）。',
      '- 若后端列表行里没有 source_api_name / target_api_name 这两个字段，就不要在前端拼字段——先在 residual_risk 里说明缺哪个字段、需要后端补什么，只把「方向」列做出来。',
      '',
      '不要改后端（收紧 list_relations 会连带改 create_relation 的 source|target 放宽校验，改动面太大）。',
    ].join('\n'),
  },
  {
    key: 'apiService',
    files: ['backend/app/features/api_catalog/services/api_service.py'],
    detail: [
      '两个独立缺陷，都在这个文件里。',
      '',
      '缺陷 1（low）move_module 允许「带子模块的模块」移到另一个一级模块下，产生 depth-3 模块树，违反本模块「最多两级」的约束。',
      '修法：在 move_module 里 is_default 判断之后、解析新父之前插入子模块检查：',
      '',
      '  if body.parent_id is not None:',
      '      has_children = (',
      '          db.query(ApiModule.id)',
      '          .filter(ApiModule.parent_id == mod.id)',
      '          .first()',
      '          is not None',
      '      )',
      '      if has_children:',
      '          raise bad_request("该模块有子模块，不能移动到另一个模块下；请先移动或删除子模块，或挂回根（parent_id=null）")',
      '',
      '挂回根（parent_id=None）仍然允许，与 delete_module 里「子模块需先处理」的语义一致。不要引入新的 helper 去重构 create_module。',
      '',
      '缺陷 2（low）list_interfaces 的 status 查询参数无合法性校验、也不做大小写归一：传小写 "active" 会静默返回空结果集，与 method 参数的处理不一致。',
      '修法（只做归一化，**不要**加 raise）：',
      '',
      '  if status:',
      '      status = status.upper()',
      '      query = query.filter(ApiInterface.status == status)',
      '',
      '只加归一化的原因：本代码库其余 6 处 status 过滤都是「未知值 -> 空集」语义，单在这里 raise 400 会引入一处孤立的严格校验。归一化即可消除静默空结果，仍保持全站一致。若 status 归一化后需要常量集合做判断就另说，但**不要**引入新异常分支。',
      '',
      '两个改动互不影响，都做。改完用 sed -n 回看两段确认。',
    ].join('\n'),
  },
  {
    key: 'debugService',
    files: [
      'backend/app/features/api_catalog/services/debug_service.py',
      'backend/app/features/business/executors/api_executor.py',
    ],
    detail: [
      '缺陷（severity medium，已对抗性验证成立）：调试执行器有两个独立的资源保护问题。',
      '',
      '缺陷 1（内存无上限）：debug_service.py 约 121-135 行用 httpx.Client(...).request() 然后取 resp.text。',
      'httpx 的 send 在返回前就把响应体全量读进内存，_MAX_RESPONSE_BODY 截断发生在那之后，完全没起到保护作用。目标返回 200MB 时进程先分配 200MB 再加一份解码副本，然后才截到 200KB。一次平台管理员的正常调试（对白名单内目标发 GET）就能把该 uvicorn worker 打挂。',
      '',
      '修法：改流式、边读边限：',
      '',
      '  with httpx.Client(timeout=httpx.Timeout(...), follow_redirects=False, trust_env=False) as client:',
      '      with client.stream(method, url, headers=headers, params=query, **send_kwargs) as resp:',
      '          status_code = resp.status_code',
      '          resp_headers = {str(k): str(v) for k, v in resp.headers.items()}',
      '          buf = bytearray()',
      '          truncated = False',
      '          for chunk in resp.iter_bytes(chunk_size=65536):',
      '              if len(buf) > _MAX_RESPONSE_BODY:',
      '                  truncated = True',
      '                  break',
      '              buf.extend(chunk)',
      '          resp_body = buf.decode("utf-8", errors="replace")',
      '',
      '要点：',
      '- 流式下 status_code 与 headers 在正文前就可读，无需先 read()。',
      '- 必须用 iter_bytes()，不能用 resp.text（后者仍会把剩余部分全读进来）。',
      '- errors="replace" 避免大响应里出现半个多字节字符时抛 UnicodeDecodeError 变成 500；原 resp.text 在 Content-Type 非 UTF-8 时会猜编码，行为不稳定。',
      '- 退出 for 即退出 with，httpx 会关闭底层流，剩余字节不读。',
      '- 若 truncated 为真，在 resp_body 末尾追加 "\\n...[已截断]"，语义与原来的截断标记一致。',
      '- 保留原有的 ConnectError / TimeoutException / HTTPError / ImportError -> bad_request 兜底，注意流式读取中抛的异常也要被这些分支接住。',
      '- 保留 outbound_target_id 与 response_time_ms 语义不变。',
      '',
      '缺陷 2（无总时限）：httpx.Client(timeout=<标量>) 会让 connect/write/read/pool 各得一份，且 read 是「每次 socket 读」级别——目标每秒吐 1 字节即可让连接无限期存活、内存无限增长。',
      '修法：把四个阶段显式拆分并把总和压回 body.timeout（T = body.timeout）：',
      'connect=0.2*T、write=0.2*T、pool=0.2*T、read=0.4*T（向下取整到合理小数，避免 0）。',
      '并把超时提示文案改成与实际一致（api_executor.py 里的文案已经是正确写法，照抄即可）。',
      '',
      '第二个文件 api_executor.py 有**同款问题**：请检查它是否也用 resp.text + 标量 timeout。若是，按同样的流式 + 分阶段 timeout 修法处理；若结构不同或没有该问题，不要动它，在 residual_risk 里写明。',
      '',
      '注意：httpx.Timeout 各分量必须 > 0。若 body.timeout 很小（比如 1 秒），分阶段后 read=0.4 秒可能过短——按你的判断取一个下限（例如各分量至少 0.1 秒），并在注释里说明为什么。',
    ].join('\n'),
  },
  {
    key: 'sensitive',
    files: ['backend/app/features/business/executors/sensitive.py'],
    detail: [
      '缺陷（severity medium，主会话已人工核实成立）：mask_request 返回的 query 字段是明文，敏感值泄漏进执行记录。',
      '',
      '现状：mask_request 里 masked_url 已经用 is_sensitive_key(k) 对 query_pairs 做了脱敏（命中则替换为 _MASKED），但返回字典里另一个 query 字段写的是：',
      '  "query": {str(k): str(v) for k, v in (query or {}).items()},',
      '原样明文。这份 snapshot 会被写进 action_execution，所以 query 里带 token / sessionid / access_key / code 之类的值会以明文落库，违反本模块「敏感值不落库」的契约。注意 URL 脱敏了但 query 字段没脱敏，两处自相矛盾。',
      '',
      '修法（最小改动，一处）：query 字段复用与 masked_url 相同的判定：',
      '  "query": {',
      '      str(k): (_MASKED if is_sensitive_key(k) else str(v))',
      '      for k, v in (query or {}).items()',
      '  },',
      '',
      '要求：',
      '- 保持字段形状不变（仍是 dict[str, str]），下游可能依赖它。',
      '- 脱敏口径必须与 masked_url 完全一致（同一个 is_sensitive_key、同一个 _MASKED 标记），不要引入第二套判定。',
      '- 不要动 mask_response / mask_body / mask_headers / _mask_context_for_storage。',
      '- 改完 grep 一遍确认该文件里没有别处把 query 明文写出去。',
    ].join('\n'),
  },
  {
    key: 'flowExecutor',
    files: ['backend/app/features/business/executors/business_flow_executor.py'],
    detail: [
      '两个独立缺陷，都在 execute_flow 里。',
      '',
      '缺陷 1（ValueError -> 500）：execute_flow 里「环境不存在或已停用」「业务流程不存在」用 raise ValueError。',
      'ValueError 不是 AppError，全局 exception handler 会把它变成 500「服务器内部错误」+ 英文信息，用户看到内部错误而非可读提示；而且这两种都是「资源不存在」语义，按本项目约定应返 404。',
      '修法：改用 app.shared.errors 的 not_found，与项目其他服务层一致：',
      '  raise not_found("环境不存在或已停用")',
      '  raise not_found("业务流程不存在")',
      '注意 import 不要造成循环导入（app.shared.errors 是共享层，安全）。',
      '',
      '缺陷 2（死循环变量，顺序信息全丢）：for seq, action in enumerate(actions): 里调用',
      '  _execute_action(db, execution, action, environment, ctx, project_id=flow.project_id)',
      '没有把 seq 传进去。seq 从未被使用，所有 action_execution.sequence 都是 0，执行记录里动作顺序信息全丢——后续查看执行明细时无法还原动作次序。',
      '修法：',
      '- 先读 _execute_action 的签名，确认它是否已有 sequence 参数（或等价字段）。',
      '- 若已有参数但未传：直接补上 seq。',
      '- 若没有该参数：给 _execute_action 加一个关键字参数，并落到 ActionExecution.sequence。',
      '- sequence 的起点与语义要与 backend/app/features/business/models/execution.py 里该列的 default / comment 保持一致（先读那一行再定 0 起还是 1 起），在注释里写清楚。',
      '',
      '两个改动互不影响，都做。改完 grep 确认 seq 确实被使用了。',
    ].join('\n'),
  },
  {
    key: 'bindingUnique',
    files: [
      'backend/app/features/business/models/business_binding.py',
      'backend/app/features/business/services/binding_service.py',
    ],
    detail: [
      '缺陷（severity medium，已对抗性验证成立）：0005 建的部分唯一索引 ix_business_binding_action_default',
      '（action_id, binding_type, WHERE is_default = true，用于保证每个 action + binding_type 最多只有一条',
      'is_default=True 的绑定）只存在于迁移文件里，ORM 模型没有声明。',
      '后果：走 AUTO_CREATE_SCHEMA 路径（不跑 Alembic、直接 Base.metadata.create_all）造出的库没有这条约束，',
      'create_binding / update_binding 允许插入多条同 action+binding_type 的默认绑定，且此时抛 IntegrityError -> 500 而非 409。',
      '（结论标题写的「ORM 无法表达」不准确，ORM 完全能表达 postgresql_where，正确说法是「ORM 未声明」。不要按「表达不了」去找手写 DDL 或事件钩子之类的 workaround。）',
      '',
      '根因修复（business_binding.py，一行）：在 __table_args__ 里补',
      '',
      '  Index(',
      '      "ix_business_binding_action_default", "action_id", "binding_type",',
      '      unique=True, postgresql_where=text("is_default = true"),',
      '  ),',
      '',
      'Index 与 text 若该文件已导入则无需新增，否则补 import。迁移里的 CREATE UNIQUE INDEX IF NOT EXISTS 是幂等的，对已建索引的库无影响。',
      '',
      '改之前必须做：用 python -c 打印该表全部索引名（含 Column(index=True) 隐式生成的），确认 ix_business_binding_action_default 不与已有索引名重名——本仓库在 api_interface.source_hash 上真实踩过「ORM index=True 与显式 Index 重名 -> DuplicateTable」的坑。',
      '',
      '加固（binding_service.py，同批做）：create_binding / update_binding 捕获 IntegrityError 转 conflict 409，',
      '这样在已有旧库（约束已由迁移建好）上的重复默认绑定也返回可读的 409 而不是 500。',
      '注意 commit/rollback 边界：本仓库约定 service 层负责 commit，捕获 IntegrityError 后要先 rollback 再抛 conflict，',
      '否则 session 处于失效状态。先读该文件现有的事务写法再改，保持风格一致。',
      '',
      '不要顺手给 FlowExecution / ActionExecution 加查询性能索引（与正确性无关，留给另一组处理）。',
    ].join('\n'),
  },
  {
    key: 'conftestDb',
    files: ['backend/tests/conftest.py'],
    detail: [
      '缺陷（severity low，已对抗性验证成立）：测试库名固定为 testplatform_test。',
      'conftest.py 的 test_database（session 作用域）在会话开头 _terminate_connections()（pg_terminate_backend）',
      '+ DROP DATABASE + CREATE DATABASE，且没有 teardown。两个 pytest 进程同时跑（本地一份 + CI 一份，或两个人各起一份）时，',
      '后启动的会 DROP 掉前者的库并 terminate 其所有连接，两边批量报 psycopg.OperationalError: connection already closed /',
      'database does not exist，失败信息看起来像产品缺陷，很容易被误判。',
      '',
      '修法：',
      '1. 库名加进程级唯一后缀，作为**单一事实源**定义在 conftest.py 里：',
      '     TEST_DATABASE_NAME = os.environ.get("TEST_DATABASE_NAME") or f"testplatform_test-p{os.getpid()}"',
      '   PostgreSQL 标识符 63 字符上限，"testplatform_test-p123456" 安全。',
      '   其他测试文件（test_01 / test_07）通过 TEST_DSN.replace(f"/{TEST_DATABASE_NAME}", ...) 继承该值，无需改动它们。',
      '',
      '2. test_database 加 teardown：会话结束后只 DROP 自己派生的库名。pid 后缀 + teardown 两半要一起上，',
      '   因为 pid 复用后可能撞上旧 schema 的残留库，只有 teardown 才让它无关紧要。',
      '   注意 CREATE / DROP DATABASE 不能在事务里执行，需保持 autocommit + 走维护库（ADMIN_DSN）连接；',
      '   先看现有写法再改，别把已有的事务处理弄坏。',
      '',
      '3. 可选收敛：conftest._terminate_connections、test_07 的 _prepare、test_01 的 _seed_into_target_database',
      '   三份 terminate+DROP+CREATE 里 CREATE DATABASE 都不带 IF NOT EXISTS，并发下同样报 DuplicateDatabase。',
      '   能抽公共 helper 就抽；**但 test_01 和 test_07 用户在改或在用，改动面大的话只做 1+2 即可**，',
      '   在 residual_risk 里写明没收敛的部分。',
      '',
      '只改 conftest.py。不要改 app 代码，不要改其他测试文件。',
    ].join('\n'),
  },
]

// ---------------------------------------------------------------- 主流程
phase('Verify')

const [vOut, f1Out] = await Promise.all([
  parallel(
    VERIFY.map((v) => () =>
      agent(verifyPrompt(v), {
        label: v.label,
        phase: 'Verify',
        schema: VERDICT_SCHEMA,
        effort: 'high',
      })
    )
  ),
  parallel(
    FIX_WAVE1.map((t) => () =>
      agent(fixPrompt(t), {
        label: 'fix:' + t.key,
        phase: 'Fix',
        schema: FIX_SCHEMA,
        effort: 'high',
      })
    )
  ),
])

const V = {}
VERIFY.forEach((v, i) => { V[v.key] = vOut[i] })

const realNew = VERIFY.filter((v) => V[v.key] && V[v.key].real)
log('裁定：' + VERIFY.length + ' 条中 ' + realNew.length + ' 条成立 —— ' +
  (realNew.length ? realNew.map((v) => v.key).join(', ') : '无'))

// ---------------------------------------------------------------- 按裁定结果决定第二波
const WAVE2 = []

if (V.importResolveDry && V.importResolveDry.real) {
  WAVE2.push({
    key: 'importService',
    files: ['backend/app/features/api_catalog/services/import_service.py'],
    detail: [
      '两个缺陷。',
      '',
      '缺陷 A（low，已验证成立）preview 响应 existing_count 恒为 0。',
      'preview 的分类只会是 NEW / CHANGED / UNCHANGED（ImportClassification 里的 EXISTING 在实现里结构上不可达），',
      'counts 也只建了这三个键，但 preview 响应硬编码 existing_count=0。前端 ImportPreview 直接展示成「已存在 0」，',
      '用户能看到 N 条明确被标为 CHANGED（即库里存在），却同时看到「已存在 0」，total 与各分项对不上。',
      '修法（方案 A，最小改动）：existing_count = counts["CHANGED"] + counts["UNCHANGED"]，',
      '这样 existing_count == total - new_count，与前端「已存在」文案自洽。',
      '**不要**移除该字段（前端在展示），**不要**去删 ImportClassification 里的 EXISTING（改动面太大）。',
      '',
      '缺陷 B（验证结论如下，按裁定为真）：',
      V.importResolveDry.repro,
      '',
      '建议修复：' + V.importResolveDry.fix,
      '',
      '实现要求：preview 与 confirm 的模块归属判定必须在「同批内新建模块」这一点上保持一致。',
      '最小改法是 resolve_dry 在预览循环内维护一个批内 module_name -> 是否将新建 的映射（或先算一遍批内将要创建的模块名），',
      '让 step 4 / step 5 的判定与 confirm 一致。不要改 confirm 的逻辑去迎合 preview。',
      '改完自己构造一个「两个接口、一个带 tags 一个不带、URL 推断出同一模块名」的例子走读一遍 preview 与 confirm 的分支，',
      '确认预览与实际一致，并把走读结论写进 verified。',
    ].join('\n'),
  })
} else {
  WAVE2.push({
    key: 'importService',
    files: ['backend/app/features/api_catalog/services/import_service.py'],
    detail: [
      '一个缺陷。preview 响应 existing_count 恒为 0。',
      '',
      'preview 的分类只会是 NEW / CHANGED / UNCHANGED（ImportClassification 里的 EXISTING 在实现里结构上不可达），',
      'counts 也只建了这三个键，但 preview 响应硬编码 existing_count=0。前端 ImportPreview 直接展示成「已存在 0」，',
      '用户能看到 N 条明确被标为 CHANGED（即库里存在），却同时看到「已存在 0」，total 与各分项对不上。',
      '修法（最小改动）：existing_count = counts["CHANGED"] + counts["UNCHANGED"]，',
      '这样 existing_count == total - new_count，与前端「已存在」文案自洽。',
      '**不要**移除该字段（前端在展示），**不要**去删 ImportClassification 里的 EXISTING。',
    ].join('\n'),
  })
}

if ((V.execution0005indexes && V.execution0005indexes.real) || (V.execution0005downgrade && V.execution0005downgrade.real)) {
  WAVE2.push({
    key: 'migration0005',
    files: [
      'backend/alembic/versions/0005_business_phase2.py',
      'backend/app/features/business/models/execution.py',
    ],
    detail: [
      '按下面两条裁定修 0005（以及必要时 models/execution.py）。',
      '',
      '裁定一（索引对齐）：real=' + (V.execution0005indexes ? V.execution0005indexes.real : '未返回') + '，severity=' +
        (V.execution0005indexes ? V.execution0005indexes.severity : '?') + '。' +
        (V.execution0005indexes ? '\n\n' + V.execution0005indexes.reasoning + '\n\n复现路径：' + V.execution0005indexes.repro +
          '\n\n建议修复：' + V.execution0005indexes.fix : '\n\n（验证 agent 未返回，按「ORM 声明的索引集合与迁移实际建的索引集合不一致」自行比对后决定）'),
      '',
      '裁定二（downgrade 未恢复唯一约束）：real=' + (V.execution0005downgrade ? V.execution0005downgrade.real : '未返回') +
        '，severity=' + (V.execution0005downgrade ? V.execution0005downgrade.severity : '?') + '。' +
        (V.execution0005downgrade ? '\n\n' + V.execution0005downgrade.reasoning + '\n\n复现路径：' + V.execution0005downgrade.repro +
          '\n\n建议修复：' + V.execution0005downgrade.fix : '\n\n（验证 agent 未返回，自行比对 0004 与 0005 的 downgrade 段后决定）'),
      '',
      '硬性要求：',
      '- **real=false 的裁定一律不改**。不要为「保持一致性」去做不可复现的理论修复。',
      '- 只补迁移里缺的、且 ORM 已声明的索引；不要删迁移里已有但 ORM 未声明的复合索引（那是既有查询索引，删了影响线上查询计划）。',
      '- 若采纳「补 ADD CONSTRAINT UNIQUE」方向：必须先确认它不会在已有重复行的库上让 downgrade 硬失败。',
      '  阶段二业务允许一个 action 有多个 binding，如果 (action_id, binding_type) 重复行是常态，裸 ADD CONSTRAINT 会在事务中途炸、库停在半迁移状态。',
      '  这种情况下要么先做去重并在 docstring 显式说明这是破坏性删除，要么判为不修（real=false）并在 residual_risk 里说明取舍。',
      '- PostgreSQL **不支持** ALTER TABLE ADD CONSTRAINT IF NOT EXISTS（那是 MariaDB 语法），幂等要用 inspector.get_unique_constraints 判存在性。',
      '- 改完用 ' + VENV + ' -c 打印两张表的 ORM 索引集合与 0005 里的建索引语句逐条比对，把比对结果写进 verified。',
      '- 不要改 backend/tests 下断言 head 的测试（用户在改 test_01）。',
    ].join('\n'),
  })
}

if ((V.ModuleTree && V.ModuleTree.real) || (V.RequestTab && V.RequestTab.real)) {
  WAVE2.push({
    key: 'apiCatalogFront',
    files: [
      'frontend/src/pages/console/ApiCatalog/ModuleTree.tsx',
      'frontend/src/pages/console/ApiCatalog/tabs/RequestTab.tsx',
    ],
    detail: [
      '按下面两条裁定修对应文件。**real=false 的一律不改。**',
      '',
      '裁定一（ModuleTree）：real=' + (V.ModuleTree ? V.ModuleTree.real : '未返回') + '，severity=' +
        (V.ModuleTree ? V.ModuleTree.severity : '?') + '。' +
        (V.ModuleTree ? '\n\n' + V.ModuleTree.reasoning + '\n\n复现路径：' + V.ModuleTree.repro +
          '\n\n建议修复：' + V.ModuleTree.fix : ''),
      '',
      '裁定二（RequestTab）：real=' + (V.RequestTab ? V.RequestTab.real : '未返回') + '，severity=' +
        (V.RequestTab ? V.RequestTab.severity : '?') + '。' +
        (V.RequestTab ? '\n\n' + V.RequestTab.reasoning + '\n\n复现路径：' + V.RequestTab.repro +
          '\n\n建议修复：' + V.RequestTab.fix : ''),
      '',
      '硬性要求：',
      '- 只改被判 real=true 的那一个文件。real=false 的文件一行都不要动。',
      '- ModuleTree 若判真，修法要让树上能覆盖全部接口：优先做法是让 listApis 传够大的 page_size（用后端 MAX_PAGE_SIZE 上限），',
      '  而不是在前端做无限滚动；若你判断无限滚动更合适，在 residual_risk 说明理由。',
      '- RequestTab 若判真，注意 raw_text 语义：用户没有编辑入口时置 null 才是 bug；有编辑入口则是用户主动清空，不该改。',
      '- 不要改 types/index.ts（用户在改）。需要局部类型调整就在本文件内断言。',
    ].join('\n'),
  })
}

phase('Fix')
const f2Out = await parallel(
  WAVE2.map((t) => () =>
    agent(fixPrompt(t), {
      label: 'fix:' + t.key,
      phase: 'Fix',
      schema: FIX_SCHEMA,
      effort: 'high',
    })
  )
)

const allFixes = FIX_WAVE1.map((t, i) => ({ key: t.key, r: f1Out[i] })).concat(
  WAVE2.map((t, i) => ({ key: t.key, r: f2Out[i] }))
)

return {
  verdicts: VERIFY.map((v) => {
    const d = V[v.key]
    return {
      key: v.key,
      claim: v.claim,
      real: d ? d.real : null,
      severity: d ? d.severity : null,
      repro: d ? d.repro : null,
      reasoning: d ? d.reasoning : null,
      verdict_fix: d ? d.fix : null,
    }
  }),
  fixes_applied: allFixes.filter((f) => f.r).map((f) => ({
    key: f.key,
    files_changed: f.r.files_changed,
    summary: f.r.summary,
    verified: f.r.verified,
    residual_risk: f.r.residual_risk,
  })),
  fixes_failed: allFixes.filter((f) => !f.r).map((f) => f.key),
  wave2_keys: WAVE2.map((t) => t.key),
}
