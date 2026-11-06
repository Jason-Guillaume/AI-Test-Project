# FunASR 独立 AI 分析与批量自动调优交付记录

日期：2026-11-06。状态：功能代码和合成验证已完成；真实运行须先完成项目配置和数据库迁移。

## 操作入口

登录后选择项目，进入 **ASR → AI 分析与调优**，也可直接打开 `/console/asr/funasr`。

1. 在项目「接口管理」导入 `POST /api/v1/transcribe/paraformer/v2`，并将服务地址配置在项目环境中。
2. 在页面选择接口和环境，按需填写鉴权请求头和凭据。凭据加密保存；接口地址、请求头和凭据在任务执行快照中加密保存。执行仍经过项目出站目标校验。
3. 填写真实响应 JSON 样本和显式字段映射，预览后点击「验证并保存响应映射」。未通过样本映射验证的绑定不能启动任务。
4. 为录音逐条上传标准答案 JSON，选定答案字段映射。每个答案保存为不可变版本，并固定到上传时的音频版本。
5. 选择至少一条已有答案的录音、文本分析模型和任务模式。确认基线参数、可搜索范围、ASR/AI 调用预算和停止条件后创建任务。后台串行处理，不依赖页面保持打开。

响应全文映射示例（路径必须来自用户提供的实际 JSON）：

```json
{"text_source":"full","text_pointer":"/<实际字段路径>"}
```

分段映射示例需要用户另行填写真实数组路径和相对于每个片段项的文字路径；有真实标注时才填写开始/结束时间、`time_unit`（`s` 或 `ms`）和说话人路径。系统不会猜测 FunASR 响应结构、补造时间或说话人。

## 已实现行为

- 独立前端入口、任务列表与详情、参数说明/范围/单位/生效条件展示、逐音频 JSON/Markdown/指标/AI 证据展示，以及暂停、继续、停止和安全补跑操作。
- 绑定当前项目的接口管理定义与项目环境；冻结接口版本、环境执行配置、响应映射、文本模型修订、评分规则、音频版本、答案版本和轮次参数。接口重导入不会静默改变已有任务。
- FunASR 请求为 JSON 顶层字段，每条音频单独注入 `audio`。标准答案、任务元数据和 `parameters` 包装均不会进入 ASR 请求。
- 保留接口请求示例作为基线。`preset_spk_num=1` 显示为强制单人，不会被文档默认的 `null` 覆盖。
- JSON 映射经明确预览；Markdown 由代码确定性生成。CER 替换/删除/插入计数、宏/微平均、覆盖率、逐样本表现和耗时由程序计算。
- 单轮分析与自动多轮调优复用现有文本模型配置。Agent 只能在用户启用的参数范围内提出最多两项变更；候选需通过旧值、类型、范围、生效条件、证据和重复参数哈希校验。退化候选不会覆盖历史最佳参数。
- 持久化 Worker 支持租约、断点恢复、夜间窗口和调用前预算预留。夜间时间按 `Asia/Shanghai` 处理。任务内 ASR 串行；旧 ASR Worker 和 FunASR Worker 使用 PostgreSQL advisory slot 共享 `ASR_WORKER_CONCURRENCY`。
- 明确失败的 AI 阶段可单独补跑。已收到响应的映射/评分错误从保存的脱敏响应重新处理，不重发 ASR；只有没有收到响应的明确失败项才允许手动补跑。提交状态未知、超时和服务端 5xx 会进入「待核实」，不会盲目重发。

## 运行与迁移

先停掉当前应用实例，备份数据库，再运行迁移：

```bash
cd backend
.venv/bin/python -m alembic upgrade head
```

迁移 `0040` 新建 `asr_api_binding`、`asr_ground_truth_version`、`asr_tuning_session`、`asr_tuning_round` 和 `asr_tuning_item`。启动 FastAPI 应用后，生命周期会启动 FunASR 后台 Worker。前端开发服务器：

```bash
cd frontend
npm run dev
```

回退前先暂停任务并停止应用/Worker，备份这些新表。执行 `cd backend && .venv/bin/python -m alembic downgrade 0039` 会删除上述五张新表及其中的任务、样本和绑定数据；不回退其他 ASR 表。

## 验证记录

- `backend/.venv/bin/python -m compileall -q backend/app/features/asr_evaluation`：通过。
- `backend/.venv/bin/python -m pytest backend/app/features/asr_evaluation/tests -q`：99 项通过（合成测试；目录中有现有 Pydantic/Starlette 警告）。合成闭环覆盖三条录音的串行批次、每轮参数一致、映射失败后复用响应、较差候选保留原最佳、暂停恢复与未知提交状态不重发。
- `npm run typecheck`、功能页单文件 ESLint、`npm test`（28 项）和 `npm run build`：通过。
- 全量 `npm run lint` 仍被工作区既有的三条 Hook 依赖警告挡住，分别位于 `ContentReviewPanel.tsx`、`JobsPage.tsx`、`RunWorkbenchPage.tsx`；本次 FunASR 页面单文件 lint 通过。
- `alembic heads` 显示 `0040 (head)`。迁移脚本在隔离 SQLite 内存库完成 upgrade/downgrade 往返；OpenAPI 检查到 16 条 FunASR 路由和响应样本字段。
- 没有迁移业务数据库，也没有访问真实 ASR 服务、内网地址或付费模型。未设置 `TEST_POSTGRES_PASSWORD`，因此没有运行 PostgreSQL 集成测试；当前迁移证据不等价于目标 PostgreSQL 数据库升级。

## 首次真实运行前需配置

- 在数据库执行 `alembic upgrade head`，并使用 PostgreSQL，以启用跨进程并发 slot。
- 项目环境目标地址和出站授权、FunASR 接口鉴权，以及已启用并授权给项目的文本分析模型。
- 至少一份真实 FunASR JSON 响应和每条录音的标准答案 JSON；在页面逐一预览并保存准确映射。当前没有通用异步提交/轮询协议或服务端幂等契约，因此只实现同步 JSON；超时/5xx 需要人工核实。
- 第一版只计算文本 CER，没有说话人错误指标，所以 `speaker_merge_threshold` 保持锁定。当前任务使用一个调优样本集，不提供独立盲测保留集；报告仅能说明所选样本集上的结果。
- 标准答案原 JSON、识别 JSON、规范化 JSON 和 Markdown 暂存于数据库答案/样本行，不使用现有 ASR 文件产物目录；单份答案上限 5 MB、接口响应上限 20 MB。部署前应确认数据库存储策略满足项目保留要求。

真实配置完成前，页面不会宣称接口已联通，也不会自行触发 ASR 或模型请求。
