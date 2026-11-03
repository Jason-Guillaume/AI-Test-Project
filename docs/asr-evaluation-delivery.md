# ASR 夜间对照评测交付与启动说明

日期：2026-11-02。分支：`codex/asr-nightly-evaluation`，基于同步后的 `origin/develop` (`773f17e`)。本次没有提交代码，也没有改动/清理用户原有未提交文件；开始前的改动仍在工作区并有 `stash@{0}` 备份。

## 实现内容

- 新增 ASR 独立后端领域、0032 迁移、`/api/v1/asr` 路由和 `backend/scripts/run_asr_worker.py`。音频 URL、接口地址和凭据加密存储；页面与导出展示脱敏值。
- 支持批量 URL 导入、连接版本、同步 JSON 与异步提交/轮询合同、参数定义/版本、诊断调用、响应大小边界和带 Range 校验的音频代理。
- 支持立即/指定时间/每日计划，固定资源版本，持久队列、租约及代次、Worker 心跳、超时恢复、部分成功、取消和不确定提交的待核实状态。
- 支持长文本的有界三方对齐、差异筛选、三组文本差异比例、结果分页、真实供应方时间戳定位和音频回听；没有可信定位时显示未定位。
- 支持片段人工确认/暂无法确认、编辑、版本冲突保护、审计历史和显式加入校对集；支持证据约束建议、参数范围校验、候选版本和独立复跑、JSON/CSV 导出。
- 参数实验默认重新请求三家模型。创建候选时可明确选择复用当前对比中的两条成功参考结果；服务端再次核验源任务、音频资源版本及成功状态，并把来源对比、运行 ID 和完成时间写入快照。系统没有可靠音频内容指纹，同一 URL 不证明远端内容未替换；复用前需人工确认内容相同。该选项不会把参考结果当成标准答案。
- 页面菜单与导航沿用现有 Console 外壳和参考图浅蓝配色；文案按方案第 3 节调整。无标准转写文本时不计算准确率；云端一致仅作为一致性事实。

## 启动

先按 [getting-started.md](getting-started.md) 配置 `backend/.env` 中的 `DATABASE_URL` 与强 `SECRET_KEY`，并准备隔离的 PostgreSQL 开发/测试环境。音频和接口凭据加密密钥可使用平台已有的 `MODEL_CONFIG_ENCRYPTION_KEY`，未单独配置时由 `SECRET_KEY` 派生。首次启动前升级数据库：

```bash
cd backend
.venv/bin/alembic upgrade head
```

分别启动后端、前端和常驻 ASR Worker：

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload --port 8001
```

```bash
cd frontend
npm run dev
```

```bash
cd backend
.venv/bin/python scripts/run_asr_worker.py
```

前端地址为 `http://127.0.0.1:5173`；后端健康检查为 `http://127.0.0.1:8001/healthz`。Worker 支持 `ASR_WORKER_ID`、`ASR_WORKER_POLL_SECONDS`（默认 1 秒）、`ASR_WORKER_CONCURRENCY`（默认 2）和 `ASR_WORKER_LEASE_SECONDS`（默认 90 秒）。媒体代理读取上限可通过 `ASR_MEDIA_MAX_BYTES` 配置，默认 2 GiB。Worker 必须持续运行，运行主机需保持唤醒并具备网络；页面会显示最近心跳/离线状态，保存计划本身不代表任务已执行。

## 验证结果

- 后端定向：`backend/.venv/bin/python -m pytest app/features/asr_evaluation/tests -q`，15 passed。
- 后端语法：`backend/.venv/bin/python -m compileall -q app/features/asr_evaluation app/execution/http scripts/run_asr_worker.py`，通过。
- 迁移：在独立 SQLite 文件上 stamp 0031 → upgrade head → downgrade 0031 → 再 upgrade head；最终 `0032 (head)`，14 张 ASR 表存在，`asr_experiment.reuse_reference_results` 存在。此项只验证新迁移的可升降级性，不替代 PostgreSQL 回归。
- 前端：`npm test` 14 passed；`npm run typecheck`、`npm run lint`、`npm run build` 均通过。
- 完整 `backend/tests` 回归未能启动：`backend/tests/conftest.py` 明确要求 `TEST_POSTGRES_PASSWORD`（或 `POSTGRES_PASSWORD`），当前未提供；没有连接或重置开发库。
- 浏览器页面验收覆盖音频、接口配置、任务、对比列表和参数实验的空态。预览使用临时本地空响应，仅模拟登录用户和空数据；未模拟云端结果。真实长音频播放、服务识别、异步恢复、人审提交、建议调用及候选复跑仍待联调。

## 页面截图

截图来自本地页面空态，仅作为布局/颜色和文案验收；没有可展示的真实三方结果或审阅记录。

| 页面 | 截图 |
|---|---|
| 音频列表 | [asr-audio-empty.jpg](asr-evaluation-validation/asr-audio-empty.jpg) |
| 接口配置 | [asr-connections-empty.jpg](asr-evaluation-validation/asr-connections-empty.jpg) |
| 评测任务与夜间计划 | [asr-jobs-empty.jpg](asr-evaluation-validation/asr-jobs-empty.jpg) |
| 识别结果对比列表 | [asr-comparisons-empty.jpg](asr-evaluation-validation/asr-comparisons-empty.jpg) |
| 候选参数对比 | [asr-experiments-empty.jpg](asr-evaluation-validation/asr-experiments-empty.jpg) |

受缺少真实服务和数据影响，方案所列完整三方结果页、人审页截图没有生成；没有用固定假结果替代。

## 回退与未完成项

- 回退应用前，先在页面暂停夜间计划、停止新提交并核对在途/待核实任务，然后停止 Worker，再回退 Web/应用版本。迁移新表可先保留，旧版本不会依赖它们。
- 0032 降级会删除 ASR 领域表及其中的任务、结果与复核数据。只有先导出并确认放弃这些数据后，才在隔离环境或经批准的维护窗口执行 `.venv/bin/alembic downgrade 0031`；不通过重建主库回退。
- 真实联调待补：待测接口合同和参数说明、两家参考服务协议/必要签名适配、有效凭据、可授权的 30 分钟以上音频 URL，以及可用的现有文本模型配置。
- 有上述条件后，需在 PostgreSQL 隔离测试环境跑全量后端回归，并完成一次完整三方夜间批次、重启恢复、回听、人工确认、建议和候选复跑验证。当前功能代码和通用协议已落地，生产接口行为不作已验证承诺。
