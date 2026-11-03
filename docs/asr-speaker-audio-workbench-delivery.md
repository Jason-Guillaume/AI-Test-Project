# ASR 说话人分段与音频工作台交付

日期：2026-11-02。分支：`codex/asr-nightly-evaluation`，基于同步后的 `origin/develop`（`773f17e6`）。实施依据：[优化方案](2026-11-02-asr-speaker-audio-workbench-optimization-plan.md)及[验收阻断报告](2026-11-02-asr-evaluation-verification-report.md)。

## 交付范围

按 S0–S5 完成了当前平台的说话人处理与单模型音频工作台，保留原三方对比页面。`/Users/a1/Desktop/studio` 只读用于了解交互，本次未修改。现有未提交修改均保留；未做 reset、stash、commit 或无关重构。

| 阶段 | 结果 |
|---|---|
| S0 盘点与基线 | 阅读编码规范、方案及验收报告；保留既有工作区内容。 |
| S1 数据与合同 | 新增 0033 迁移、音频版本快照、处理运行/队列、转写片段、说话人结果/区间、关联版本、审计及媒体分析实体。时间统一使用原始音频时间轴毫秒；原始 speaker_id、稳定片段 ID、声道、有效置信度和原始 payload 独立保留。 |
| S2 后台处理 | 新增可查询、恢复和单独重试的说话人及媒体分析任务阶段。按音频版本、连接和参数对独立分段任务去重；结果按版本关联多条 ASR。重试失败的说话人任务不会重新提交三家转写。支持区间-only 与携带文本区间两类 JSON 映射。 |
| S3 关联与人工校对 | 关联采用可信时间区间；允许未知、混合归属和重叠，不以文本长度或标点估算归属。人工改名/确认保存修订与审计；未对齐文本仍保留全文。 |
| S4 页面与媒体 | 增加单模型工作台、全文/对话切换、说话人筛选、人数/区间/发言统计、阶段状态、回听联动、高亮、确认和 JSON/TXT 导出。播放器复用单一 AudioElement；音频信息右侧抽屉按需请求并分组展示来源、原文件、后台分析和当前播放状态；请求参数单独查看。波形峰值由后端按需提供，前端 `preload="none"`，不为默认绘制而下载整段音频。 |
| S5 修复与验收 | 修复验收报告 R1–R7；R8 在 1101–1300px 时折叠右侧建议栏并让三方卡片容器横向滚动。执行 ASR 定向回归、前端检查、隔离迁移和合成数据浏览器验收。 |

## 验收阻断修复

- **R1–R6**：修复计划创建入口、对齐尾部/不等长替换/500 块截断、结果与队列完成的事务原子性、音频版本快照、后台运行超时边界及明确远端失败处理。
- **R7**：转写片段存原文 Unicode 偏移和稳定 ID；回听映射使用对应偏移，重复短句不再跨多个出现位置合并时间。
- **R8**：建议栏响应断点提前到 1300px，三列内容独立横向滚动；不压进右栏。
- **真实服务缺口**：模型接口合同和凭据未提供，浏览器与测试仅使用明确标注的合成数据，没有调用真实云端 ASR/说话人模型。

无标准答案时不输出准确率；云端一致只记录为文本一致，不视为正确。建议保留证据引用和当前连接可调参数限制；不把未知参数或缺失时间编造成确定事实。

## 启动与配置

先配置 `backend/.env` 的 `DATABASE_URL`、`SECRET_KEY`，并为测试使用独立 PostgreSQL 库。连接密钥使用平台已有的 `MODEL_CONFIG_ENCRYPTION_KEY`；若未单独设置，则由 `SECRET_KEY` 派生。升级数据库：

```bash
cd /Users/a1/Desktop/ai-test-project/backend
.venv/bin/alembic upgrade head
```

分别启动 API、前端和常驻 Worker：

```bash
cd /Users/a1/Desktop/ai-test-project/backend
.venv/bin/uvicorn app.main:app --reload --port 8001
```

```bash
cd /Users/a1/Desktop/ai-test-project/frontend
npm run dev
```

```bash
cd /Users/a1/Desktop/ai-test-project/backend
.venv/bin/python scripts/run_asr_worker.py
```

浏览器打开 `http://127.0.0.1:5173`，选择项目后在「ASR 评测 → 接口配置」建立转写连接和「说话人分段模型」连接；再在任务/工作台为音频版本启动独立说话人分析。页面中的演示默认映射为 JSON Pointer：`segments_pointer=/turns`、`start_pointer=/start_ms`、`end_pointer=/end_ms`、`speaker_pointer=/speaker_id`、`time_unit=milliseconds`；若供应方字段不同，只需配置映射。可选 `segment_text_pointer`、置信度和声道映射。提交前以供应方协议确认字段及时间单位。通用适配器没有猜测厂商签名算法、重定向和分片拼接策略。

主要可选环境变量：

| 变量 | 默认值 | 用途 |
|---|---:|---|
| `ASR_WORKER_ID` | 自动生成 | Worker 实例身份 |
| `ASR_WORKER_POLL_SECONDS` | `1` | 持久队列轮询间隔 |
| `ASR_WORKER_CONCURRENCY` | `2` | ASR 进程并发上限 |
| `ASR_DIARIZATION_CONCURRENCY` | `1` | 说话人远端请求并发上限 |
| `ASR_WORKER_LEASE_SECONDS` | `90` | 队列租约时长 |
| `ASR_MEDIA_MAX_BYTES` | 2 GiB | 播放/媒体读取的大小上限 |
| `ASR_MEDIA_ANALYSIS_MAX_BYTES` | 2 GiB | 后台音频解析下载上限 |
| `ASR_MEDIA_ANALYSIS_TIMEOUT_SECONDS` | `7200` | 后台解析超时；代码上限 21600 秒 |
| `ASR_FFPROBE_PATH` | 自动查找 `ffprobe` | 可选原文件信息解析器路径 |
| `ASR_FFMPEG_PATH` | 自动查找 `ffmpeg` | 可选音频解码/峰值分析器路径 |

媒体分析使用单个独立进程内执行槽位，不占用 ASR/说话人 HTTP 线程。缺少解析器、源不可达或数据超限时保留任务状态并明确显示未知/不可用，不伪造波形或信号统计。

## 验证结果

- 后端 ASR 测试与旧报告 7 项隔离复现：`backend/.venv/bin/python -m pytest backend/app/features/asr_evaluation/tests docs/asr-evaluation-validation/review_reproductions_20261102.py -q --tb=short`，**34 passed**。
- 前端：`npm test` **14 passed**；`npm run typecheck`、`npm run lint`、`npm run build` 全部通过。构建输出包含独立 `RunWorkbenchPage` 懒加载分块。
- 迁移：隔离临时 SQLite 从 0031 stamp 升级至 head，验证新增表与连接 `task_type` 列；再降到 0032，空 schema 下通过。未迁移开发数据库。
- 浏览器：临时 localhost API + 合成项目/录音验证工作台全文、原始标签/人工名称、未知和重叠片段、后台阶段、音频信息抽屉、请求参数独立查看。开始播放后打开音频信息，抽屉显示播放器约 0.05 秒且播放中，关闭不会将播放头回到 0。波形峰值由 API 实际返回；无真实模型请求。
- 完整三方比较路由在此次合成预览中的列表接口没有夹具响应，显示加载失败；因此 R8 页面在真实三方比较数据下未完成浏览器截图复验。CSS 断点已按报告范围修正，ASR 业务测试覆盖相关差异逻辑。此前独立报告中的两项全量 PostgreSQL 回归失败来自其他 Web UI/治理用例，现有修改未判定其来源，也未宣称全量测试通过。
- 浏览器验收截图以本次交付消息中的 CUA 内联截图呈现，未另存文件。浏览器工具只允许 `http/https` 导航，截图写入项目目录的尝试被该策略拒绝；当前运行环境的系统截屏命令也未能访问显示设备。没有使用其他方式绕过该限制。

浏览器页面内的合成区间含有超出演示 WAV 时长的测试边界，用于核验重叠/未知显示，不代表一段真实一致的录音结果；不要将其用于产品演示或质量结论。

## 回退

1. 在页面暂停相关夜间计划，停止新建任务，检查在途与不确定提交；停止 ASR Worker，再回退前端/后端应用版本。
2. 可以先保留 0033 表以便旧应用回退后仍可回查。若需降级数据库，先导出并确认放弃说话人/媒体处理数据，删除/导出说话人连接；迁移自带说话人连接保护。维护窗口按顺序执行：

   ```bash
   cd /Users/a1/Desktop/ai-test-project/backend
   .venv/bin/alembic downgrade 0032
   ```

3. `0033` 降级会删除 0033 新增的说话人/媒体/处理记录、音频版本以及 0032 记录上的音频版本引用字段；它不是无损回退。若保留新产生的数据，恢复 DB 备份并继续使用兼容应用，不要强制删除表。

## 待完成项

- 等待真实说话人模型协议、认证方式、可授权音频 URL 与凭据；用供应方样本确认区间-only/文本区间映射、状态轮询、超时和重试语义。
- 在隔离 PostgreSQL 环境完成多 Worker 并发领取/宕机租约恢复，以及长于 30 分钟 Range 播放和后台音频解析/峰值负载验收。
- 补齐临时合成预览的三方对比列表夹具，再在 1101、1200 和 1300px 检查 R8 的三方比较数据页面，并将两张工作台截图归档至 `docs/asr-evaluation-validation/`。当前交付消息附有工作台及音频信息抽屉截图。
- 若供应商要求长音频切片，需要先提供跨切片稳定说话人归一与原始时间映射合同；当前适配器不将各分片内的同名 speaker 标签假定为同一个人。
