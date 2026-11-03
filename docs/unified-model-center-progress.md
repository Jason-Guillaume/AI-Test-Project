# 统一模型中心开发记录

开发起始：2026-11-02；完成记录：2026-11-03。

## 基线与保护范围（M0）

- 开发分支：`codex/asr-nightly-evaluation`；初始 HEAD 与 `origin/develop` 同为 `773f17e`。
- 开始前 Alembic head：`0033_asr_speaker_audio_workbench`；本次新增 `0034_unified_model_center`。
- 开始时工作区已有多处后端、前端和文档未提交修改，包含既有 ASR 夜间评测、说话人工作台及 Agent/任务改动；全部保留，未重置、未提交。
- 已完整阅读编码规范、统一模型中心方案、说话人工作台方案与交付记录，并结合 ASR 验收报告处理关联阻断。

## 阶段记录

### M0 盘点与正确性基线

- 盘点旧 `ModelConfiguration`、`AsrConnection`、ASR 参数集、任务/计划快照、成员授权与文本默认值。
- 确认项目当前 head 为 0033；新迁移从 0034 开始，不改写历史迁移。
- 保留既有说话人阶段、音频版本、播放器与抽屉等能力，统一中心通过兼容投影被原 ASR 调用方使用。

### M1 统一目录与兼容迁移

- 新增资源、连接修订、加密凭据、参数方案、旧资源映射、项目授权、用途默认、后台诊断记录和任务槽位数据模型及 API。
- 0034 回填旧文本模型 ID/domain_id、参数、Key 密文引用、默认/备用；回填 ASR 连接与参数集、历史任务和计划角色槽位。旧表和历史任务快照保留。
- 旧文本与 ASR 管理写入路径现同步更新统一目录；ASR 任务和说话人阶段使用统一资源解析，兼容 API 投影保留原有调用合同。
- 旧 `/console/asr/connections` 页面不再保留第二份配置表单，旧书签重定向至模型中心 ASR 页签；旧管理 API 仅作为同步写入规范目录的兼容桥接。
- 平台共享资源与项目私有资源同页管理；项目模型可用列表继续按项目授权过滤，诊断明确提交后才进入后台调用。

### M2 类别、适配器、能力、参数方案与默认策略

- 分离 `TEXT_GENERATION / ASR / DIARIZATION`、provider、adapter、capability 与任务槽位角色；未注册 adapter 服务端拒绝，目录只列实际注册实现。
- 当前提供 OpenAI 兼容聊天适配器和通用 JSON HTTP ASR/说话人适配器。参数定义经 JSON Pointer 做类型、范围、枚举与敏感值校验；连接与多版本参数方案独立。
- 新任务的 TEST、REFERENCE_A、REFERENCE_B、DIARIZATION 分别选择资源/修订/参数方案；相同 ASR 资源可在不同实验担任不同角色。
- 默认按类别和用途绑定，评测关闭自动换模型；文本与 ASR/说话人不得跨类别兜底。
- 页面提供平台/项目资源、连接版本、参数版本、能力、授权、复制、导入预检及明确的后台诊断操作；无鉴权凭据不要求伪填 Token，仍执行项目出站授权。
- ASR/说话人参数表单按当前连接声明动态生成语言、热词、VAD、标点、时间戳及其他字段控件，并保留 JSON 编辑入口。创建表单中的常见 ASR 字段是可删除示例，维护者必须按供应商 API 文档确认后再保留。

### M3–M4 调用方接入与页面验收

- `/admin/model-configs` 保留为模型中心兼容入口，新增控制台模型中心路由与导航。
- ASR 新任务表单和说话人独立处理阶段选择项目可用模型的固定修订及参数版本；原三方对比、工作台播放器、音频信息抽屉和人工确认路径保留。
- 批量导入仅接受非敏感配置；预检与保存不调用模型。诊断任务异步执行并保存状态/脱敏摘要。
- 浏览器以隔离 PostgreSQL 数据库中的合成 Text/ASR/DIARIZATION 资源验收。模型中心 ASR 列表及新增表单可见，动态字段控件已显示；本地浏览器截图随开发交付消息附出，未通过真实厂商服务诊断。
- 2026-11-03 复验：旧 `/console/asr/connections` 路由实际跳转到 `/console/model-center?category=ASR`，并选中 ASR 页签；能力勾选项来自当前后端 manifest。
- 最终前端 test/lint/typecheck/build 复跑通过；已停止验收 API/Vite 进程并删除本任务创建的合成验收数据库。开发分支仍为 `codex/asr-nightly-evaluation`；没有提交任何文件。相关跟踪文件的 `git diff --check` 无输出。

### M5 验证

- 定向后端：`30 passed`（模型中心权限/槽位/加密/适配器/导入 + ASR 核心/回归）。
- 隔离 SQLite 迁移脚本：0033→0034、0034→0033→0034 通过；检查旧 ID、默认、参数和历史任务/计划槽位。
- 前端：`npm test` 14 项通过；`npm run lint`、`npm run typecheck`、`npm run build` 通过。
- 后端完整回归在隔离 PostgreSQL 数据库执行：1071 passed，2 failed。失败分别是 `test_real_console_create_confirm_debug_report` 项目选择 UI 前置状态，以及 `test_skill_usage_read_model_counts_distinct_runs_and_limits_recent_tasks` 预期最新任务排序；均与统一模型中心无关。无开发库重置。

## 未完成与待验证

- 未提供真实 ASR/说话人厂商协议示例、凭据和出站授权配置。通用 JSON HTTP 可配置适配器及合成数据闭环已实现；真实同步/异步任务、厂商签名、长音频限制、费用和识别质量待真实联调验证。
- Anthropic 原生协议及其他未注册协议不会因 provider 名称而被认定为已支持；应在明确实现适配器后再启用。
- 完整后端回归中的两个既有失败未在本任务修复，以免扩大到无关功能。
- 本地浏览器截图通过交付消息展示；当前仓库没有独立落盘的 PNG 截图文件。
