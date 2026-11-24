# 缺陷新增、接口用例和飞书分享优化方案

基于 2026-11-18 工作区代码（HEAD `73aff15`）静态核查。文件路径均相对于 `/Users/a1/Desktop/ai-test-project`。

## 1. 缺陷新增和编辑补齐预期结果、实际结果

**现状。** 分享弹窗和免登录页已有这两个字段名，但 `Bug` 没有对应字段，分享服务写入快照的是 `None`。现有 `api_response` 是接口定位用的响应正文，仍作为接口信息单独展示。内部详情也应补上目前仅在编辑表单中可见的复现步骤。 [缺陷模型](../backend/app/features/defects/models/bug.py#L66) · [快照占位](../backend/app/features/defects/services/share_service.py#L621) · [内部详情](../frontend/src/pages/console/Defects/index.tsx#L497)

**改动。** 在当前迁移链追加 `expected_result`、`actual_result` 两列，建议均为可空多行文本，每项上限 4,000 字，前后端一致。单条新增、批量新增、编辑、列表及详情响应都接通。编辑时省略字段保留原值，显式 `null` 或清空输入清掉原值。旧缺陷页面显示「未填写」，无需从描述或响应正文回填。批量粘贴兼容原六列，新字段追加为第七、八列并同步界面说明。内部详情和公开页保留换行。 [创建与编辑契约](../backend/app/features/defects/schemas.py#L65) · [创建与批量共用写入](../backend/app/features/defects/services/defect_service.py#L166) · [响应映射](../backend/app/features/defects/router.py#L51) · [前端类型](../frontend/src/features/defects/contracts.ts) · [批量表单](../frontend/src/pages/console/Defects/BatchCreateBugsModal.tsx) · [粘贴解析](../frontend/src/features/defects/batchCreateUtils.mjs#L93)

## 2. 接口用例允许零步骤创建和草稿转正

**现状。** 「测试用例 → 接口 → 手工用例」已只提交名称、优先级、测试维度和方向，`TestCaseCreate` 无步骤字段。另一条入口「生成草稿 → 编辑草稿」要求填写步骤，`DraftUpdateRequest.steps` 拒绝空数组，草稿转正又经过工具共用的 `DesignCase` 校验。参数已配置的接口用例可以无步骤执行。执行器需要关联 `api_id`，没有步骤时读取空配置并使用已有的请求构造逻辑。 [手工新增](../frontend/src/pages/console/TestManagement/TestCases.tsx#L499) · [创建契约](../backend/app/features/test_management/schemas/cases.py#L23) · [草稿表单](../frontend/src/pages/console/TestManagement/GenerationWorkbench.tsx#L245) · [草稿契约](../backend/app/features/test_management/schemas/generation.py#L36) · [转正](../backend/app/features/test_management/services/generation_service.py#L566) · [执行器](../backend/app/features/test_management/executors/adapters/api.py#L30)

**改动。** 手工新增保持零步骤。草稿编辑按批次 `direction` 区分，API 方向步骤可选，允许用 `[]` 明确清空。后端根据数据库中的批次方向校验更新和转正，给持久化的 API 草稿使用支持空步骤的校验契约，保留共享工具模型和其他方向原有的校验行为。质量检查对 API 空步骤不报 `STEPS_EMPTY`，预期结果仍按现有规则检查并写为断言。已有步骤和配置继续可读、可用。无步骤的执行回归用已关联接口的用例验证。 [质量检查](../backend/app/features/test_management/services/generation_quality.py#L45) · [工具模型](../backend/app/tools/builtin/case_generation/contracts.py#L21) · [请求配置回退](../backend/app/features/test_management/executors/preparation.py#L216)

## 3. 单次推送一张飞书卡片和一个入口

**现状。** 批量推送接口最多接收 30 条，同一项目内每 8 条触发一次 Webhook。卡片为每条缺陷增加一个按钮，弹窗也逐条返回链接。列表保存了跨页选择的 ID，但打开批量推送弹窗时只从当前页 `data.items` 组装缺陷，可能出现选择数量与实际推送数量不同。 [分片发送](../backend/app/features/defects/services/share_service.py#L301) · [数量契约](../backend/app/features/defects/schemas_share.py#L32) · [卡片构造](../backend/app/orchestration/report_delivery/card_builder.py#L96) · [勾选入口](../frontend/src/pages/console/Defects/index.tsx#L383) · [推送弹窗](../frontend/src/features/defects/components/DefectShareModal.tsx#L77)

**推荐设计。** 单条复用现有免登录详情。多条增加一个批次分享记录，绑定本次的各条 `DefectShareLink`，由批次保存公开标识、凭证哈希、有效期、渠道和投递状态。飞书卡片只放已授权的简短摘要、缺陷数和一个「查看缺陷」按钮。单次请求只发一次 Webhook，批量响应包含一个可复制的批次 URL 和 `card_count=1`，同时保留逐条分享状态供缺陷历史查询。推送弹窗预览用完整的同项目选中 ID 与服务端实际去重数量。超过现有 30 条时在确认前提示。

批次入口沿用 `/public/defects/share/` 路由体系，例如 `/public/defects/share/batch/:batchId#token=…`。首屏返回缺陷摘要，选择某条时再读取正文和附件，复用单条页面的展示和「已解决」操作。批次下每条公开读取、附件读取、处理写入都校验批次与条目归属及有效状态。撤销一条后仅移除该条，整批撤销或过期后整个入口不可访问。旧单条链接和旧历史仍按原规则使用。

单条和批量都以确认操作的请求键先保存分享及待发送记录，原子占用投递后调用 Webhook。同一请求键的双击或网络重试复用同一分享和投递状态，分享凭证明文仍仅在签发时返回。同键异载荷返回冲突。当前审计记录是在 HTTP 调用后才写入，单靠审计的唯一键无法避免重复投递。明确失败后可从历史整批重试，每次仍只调用一次 Webhook。网络超时可能发生在飞书收件之后，显示「投递结果待确认」，由用户查看群消息后显式重发。历史里的批次重试和单条重试应分别对应各自分享对象。 [分享模型](../backend/app/features/defects/models/share.py) · [内部接口](../backend/app/features/defects/share_router.py) · [现有投递记录写入](../backend/app/platform/notifications/services/feishu_service.py#L138) · [审计模型](../backend/app/platform/notifications/models/notification_record.py) · [历史组件](../frontend/src/features/defects/components/DefectShareHistory.tsx)

## 4. 免登录网页展示完整缺陷和内嵌附件

**现状。** 附件已写入 `bug_attachment`，只有登录后的缺陷接口支持下载。公开接口只有详情、计数和已解决，没有附件读取。缺陷表本身的接口信息尚未进入快照。请求和响应的旧分享选项只读取关联执行或安全记录。另有一处字段映射缺口，授权键 `reporter`、`assignee`、`source_summary` 等与响应键 `reporter_name`、`assignee_name`、`sources` 不一致，出参过滤可能丢失已授权内容。 [附件模型](../backend/app/features/defects/models/attachment.py) · [登录态附件接口](../backend/app/features/defects/router.py#L195) · [快照和来源](../backend/app/features/defects/services/share_service.py#L597) · [公开过滤](../backend/app/features/defects/services/share_service.py#L787) · [公开路由](../backend/app/features/defects/public_router.py)

**公开字段。** 默认勾选缺陷本身可分享的字段，包括分类、描述、复现步骤、预期与实际、环境、人员、创建时间、接口方法与地址、脱敏后的请求头、请求体、响应，以及附件。发送前可以取消具体字段或附件授权。按授权键显式映射公开字段，关联证据继续按具体授权过滤。公开页面正文以推送快照为准，当前状态和处理结果沿用现有实时逻辑。调整当前文本截断策略，让新增结果和接口正文在各自已允许的输入长度内完整显示，凭证、敏感头、查询参数及内部路径仍按公开规则过滤。 [分享白名单](../backend/app/features/defects/services/share_service.py#L67) · [弹窗字段](../frontend/src/features/defects/components/DefectShareModal.tsx#L12) · [详情页面](../frontend/src/pages/public/DefectShare/index.tsx#L140)

**附件展示。** 推送时仅保存当时已上传且授权的附件引用及安全元数据，内容继续读取原附件。后续上传的附件通过重新创建分享纳入，源附件删除立即失效，页面可显示「附件已删除」。使用分享凭证经 `Authorization` 读取附件，服务端逐次校验有效期、撤销、缺陷软删除、附件公开范围及关联归属。页面内直接呈现常见图片、PDF 和纯文本日志，并显示文件名、大小和下载入口。其余类型也显示在附件区并提供下载。由服务端核验实际格式，HTML、SVG 等主动内容只走下载，保留 `nosniff`、`no-store` 和现有限流策略。图片和其他适用预览通过受控 Blob URL 渲染，按需加载、卸载时释放。生产 CSP 只为实际预览方式开放所需指令。 [公开客户端](../frontend/src/features/defects/api/publicShare.ts) · [凭证读取](../frontend/src/features/defects/api/shareToken.ts) · [公开页样式](../frontend/src/pages/public/DefectShare/share.css) · [生产代理与 CSP](../frontend/nginx.conf#L19)

**提交和部署。** 目前缺陷创建成功即关闭表单，附件在之后上传，快速推送可能截到不完整的附件列表。保存状态覆盖附件上传阶段，附件成功后再允许从该流程推送；部分失败显示未上传文件和重试入口。生产通过 `PUBLIC_APP_BASE_URL` 生成飞书用户可访问的 HTTPS 地址，确认反代的 `/public/`、`/api/` 和附件上传大小限制。使用接近当前 10 MiB 上限的文件走一次生产镜像上传与预览，避免只测 Vite。 [当前创建成功回调](../frontend/src/pages/console/Defects/index.tsx#L181) · [附件上传流程](../frontend/src/pages/console/Defects/index.tsx#L598) · [设置示例](../backend/.env.example#L43) · [部署配置](../compose.yaml#L32)

## 实施顺序和验收

1. 先完成缺陷字段迁移、表单和回显，同时验证接口用例零步骤创建。测试从当前 Alembic head `0093` 升级，旧数据、新建、批建、修改、清空均可读取。API 草稿清空步骤后仍可转正并保留断言，已绑定接口的零步骤用例可执行，其他方向的现有规则通过回归。
2. 再打通单条免登录详情和附件。用含图片、PDF、日志及普通下载文件的缺陷验证网页，检查全部已授权字段和附件。验证未勾选字段、未授权附件、跨缺陷或跨批次、旧分享、源文件删除、撤销、过期和软删除等边界。
3. 最后实现批次入口和投递幂等。用飞书 Webhook 测试桩分别推送 1、8、9、30 条，逐组断言只收到 1 次 POST、1 张卡、1 个详情按钮，网页能查看该组的全部缺陷。再测跨页选择、并发重复确认、确定发送失败后的整批重试和超时状态。使用真实测试群分别验证飞书移动端和桌面端，点开按钮后可查看附件并在允许时逐条提交「已解决」。

现有回归入口包括 [缺陷 CRUD](../backend/tests/test_08_defects.py)、[分类与批建](../backend/tests/test_91_bug_category_and_batch.py)、[公开分享](../backend/tests/test_89_defect_public_share.py)、[权限与敏感字段](../backend/tests/test_89b_defect_share_security.py)、[卡片可靠性](../backend/tests/test_89c_feishu_card_reliability.py)、[用例管理](../backend/tests/test_14_test_management.py)、[草稿审核](../backend/tests/test_48_case_generation_review.py)、[批建解析](../frontend/tests/defectBatchCreate.test.mjs)、[缺陷分享 E2E](../frontend/e2e/defect-public-share.spec.ts) 和 [用例生成 E2E](../frontend/e2e/case-generation.spec.ts)。

## 可直接交给 Agent 的提示词

```text
在 /Users/a1/Desktop/ai-test-project 实现缺陷新增、接口用例和飞书分享优化。先读 docs/defects-feishu-optimization-plan.md，核对当前分支和迁移 head，然后直接修改、验证并交付。以下路径均相对于仓库根目录。

1. 缺陷新增、批量新增、编辑、内部详情和免登录详情接通 expected_result、actual_result。沿实际 Alembic head 加一个迁移，基线是 backend/alembic/versions/0093_bug_api_fields.py。使用可空多行文本，每项上限 4000，旧数据保持 NULL；部分更新区分省略和清空。批量表单与粘贴在原六列后追加可选两列。通用实际结果与 api_response 分别保存和展示。
   路径：backend/app/features/defects/models/bug.py、schemas.py、router.py、services/defect_service.py；frontend/src/features/defects/contracts.ts、batchCreateUtils.mjs、batchCreateUtils.d.mts；frontend/src/pages/console/Defects/index.tsx、BatchCreateBugsModal.tsx。

2. 接口用例新增阶段不要求写步骤。手工创建已无步骤输入，验证该入口；把 API 方向生成草稿的步骤设为可选，允许空数组保存并转正，保留预期结果和断言。前端用批次方向显示规则，后端用数据库里的批次方向校验，保留其他方向、旧有步骤配置及共享生成工具契约的现有行为。验证关联 api_id 的零步骤用例可执行。
   路径：frontend/src/pages/console/TestManagement/TestCases.tsx、GenerationWorkbench.tsx；backend/app/features/test_management/schemas/cases.py、schemas/generation.py、services/generation_service.py、services/generation_quality.py、executors/adapters/api.py、executors/preparation.py；backend/app/tools/builtin/case_generation/contracts.py。

3. 同一项目单条或批量确认推送时只调用一次飞书 Webhook，只产生一张卡和一个查看按钮。保持 30 条上限，移除每 8 条分片和每条按钮，修复跨页勾选。单条进入现有详情，多条进入新批次网页，显示本次所选全部缺陷并复用每条详情和处理能力。批次链接带独立公开标识和哈希凭证，逐条分享继续承担快照、权限和历史。预览、结果弹窗及批次重试各围绕一个批次链接。发送前原子登记请求键，避免双击及同键并发重复投递。明确失败可重试，超时结果待确认。已有分享链接、历史和权限按既有契约兼容。
   路径：backend/app/features/defects/{models/share.py,schemas_share.py,share_router.py,public_router.py,services/share_service.py}；backend/app/orchestration/report_delivery/card_builder.py；backend/app/platform/notifications/{services/feishu_service.py,models/notification_record.py}；frontend/src/features/defects/{contracts.ts,api/defects.ts,components/DefectShareModal.tsx,components/DefectShareHistory.tsx}；frontend/src/pages/console/Defects/index.tsx；frontend/src/app/App.tsx。

4. 分享默认纳入缺陷本身所有可公开的已填内容和已上传附件，保留取消勾选和脱敏。修复白名单与响应字段名映射，补齐接口缺陷自己的请求与响应，和关联执行证据保持各自授权。用附件引用快照锁定发送范围，网页里直接显示图片、PDF 和纯文本日志；所有附件列出文件名、大小和下载入口。附件按现有分享 Bearer 和生命周期鉴权，校验批次、缺陷与附件归属，安全核验 MIME，使用受控 Blob 与最小 CSP 权限。协调创建和附件上传的完成状态，实际上传失败的文件可重试。
   路径：backend/app/features/defects/{router.py,models/attachment.py,public_router.py,schemas_share.py,services/share_service.py,services/public_rate_limit.py}；frontend/src/features/defects/api/{publicShare.ts,shareToken.ts}；frontend/src/pages/public/DefectShare/{index.tsx,share.css}；frontend/nginx.conf；backend/.env.example；compose.yaml。

5. 按方案验收。至少验证升级、缺陷字段新增/编辑/清空、API 用例和草稿零步骤、兼容旧分享以及公开附件的授权与内嵌展示。对 1、8、9、30 条分别用测试桩断言一次 POST、一张卡和一个入口，并测试选中跨页、重复确认、批次重试及超时。执行相关 pytest、npm test、npm run typecheck、npm run build 和针对性的 Playwright 用例，给出实际结果。真实飞书仅使用用户已授权的测试群 Webhook，分别核对移动端和桌面端。交付时列出改动文件、迁移、配置和每项验证结果。
```
