# 统一模型中心交付记录

日期：2026-11-03。开发记录见 [unified-model-center-progress.md](unified-model-center-progress.md)。依据：[统一模型中心优化方案](2026-11-02-unified-model-center-optimization-plan.md)、[说话人工作台优化方案](2026-11-02-asr-speaker-audio-workbench-optimization-plan.md) 与 [说话人工作台交付记录](asr-speaker-audio-workbench-delivery.md)。

## 变更概览

- 新增 `0034_unified_model_center`，建立统一模型资源、连接修订、加密凭据、参数方案版本、旧资源映射、项目授权、用途默认、后台诊断和任务槽位。
- `/admin/model-configs` 是模型中心唯一管理入口，由平台管理员维护文本推理、ASR 转写、说话人分段资源、修订、参数、能力、授权与显式诊断；管理页可切换项目范围。
- `/console/model-center` 与旧 `/console/asr/connections` 书签保留为兼容跳转，转入受平台管理员权限保护的后台页面；普通用户在 ASR 工作区只选择已授权模型，不管理模型资源。旧 API 写入仅作同步规范目录的兼容桥接。
- provider、类别、注册 adapter、adapter 能力与本次任务槽位分别记录。首期可选协议仅含 OpenAI 兼容聊天和通用 JSON HTTP ASR/说话人；未注册协议由后端拒绝，不按供应商名称推断协议。
- 连接地址/密钥与参数方案分离。同一部署可以拥有多个参数方案版本。ASR 的语言、热词、VAD、标点、时间戳等表单依据模型连接声明动态生成；新建表单的常见字段是可编辑示例，按实际供应商文档确认后再保留，不能作为联调通过的证明。
- TEST、REFERENCE_A、REFERENCE_B、DIARIZATION 是任务槽位，不是模型永久角色；同一 ASR 资源可在不同运行中作为不同角色，并为各槽位选择独立版本和参数方案。
- 普通任务选择器只读取当前项目可用资源摘要。平台共享模型需明确项目授权；项目私有资源仍限所属项目。凭据仅加密保存并返回是否配置，复制模型不复制密钥。
- 默认策略按模型类别与用途绑定；评测自动备用关闭，校验同类别，不能以其他类别兜底。
- 导入预检拒绝嵌套敏感字段。打开模型页、编辑或保存不自动访问模型；只有用户明确发起诊断且确认可能联网/计费后才执行后台诊断。
- 旧 ASR 连接写入兼容投影继续供播放器、三方对比、音频版本、说话人独立阶段、人工确认和参数复跑使用；已有历史运行快照不被重写。

主要实现位置：

- 后端领域、服务和路由：[model_center_service.py](../backend/app/platform/model_configuration/services/model_center_service.py)、[center_router.py](../backend/app/platform/model_configuration/center_router.py)、[models.py](../backend/app/platform/model_configuration/models.py)
- 迁移：[0034_unified_model_center.py](../backend/alembic/versions/0034_unified_model_center.py)
- 前端 API 和页面：[modelCenter.ts](../frontend/src/features/model-configuration/api/modelCenter.ts)、[ModelCenterPage.tsx](../frontend/src/pages/console/ModelCenterPage.tsx)
- 迁移往返检查：[verify_unified_model_center_migration.py](../backend/scripts/verify_unified_model_center_migration.py)

## 迁移与兼容验证

初始 Alembic head 为 `0033_asr_speaker_audio_workbench`，本次迁移号为 `0034`。回填保留旧 `ModelConfiguration.id`、`domain_id`、加密 Key 密文及文本默认/备用关系；旧 ASR 连接和参数集建立资源/修订/参数映射，并为历史任务及计划建立槽位引用。原旧表和历史快照保留。兼容写入口同步维护规范目录，任务执行经统一资源解析及原权限校验。

隔离 SQLite 迁移验证结果：

- 以 0033 结构 stamp 后升级至 0034：通过。
- 从 0034 回退至 0033 再升级：通过。
- 核对旧整数 ID、默认项、参数方案及历史任务/计划槽位引用：通过。
- 测试使用临时隔离数据库；没有重置或迁移开发库。

共享项目模型的可见性由授权表控制；读取项目可用模型、创建任务槽位、选择版本和参数时服务端复核类别、项目权限及引用关系。凭据不会经可用模型接口返回。

## 测试与结果

定向后端命令（在 `backend` 目录执行）：

```bash
.venv/bin/python -m pytest -q \
  app/platform/model_configuration/tests/test_model_center.py \
  app/features/asr_evaluation/tests/test_regressions.py \
  app/features/asr_evaluation/tests/test_core.py
.venv/bin/python scripts/verify_unified_model_center_migration.py
```

结果：**30 passed**；迁移脚本前向升级、降级、再升级通过。

前端（在 `frontend` 目录执行）：

```bash
npm test
npm run lint
npm run typecheck
npm run build
```

结果：**14 项测试通过**；lint、typecheck 和生产构建通过。

完整后端回归在隔离 PostgreSQL 测试库执行，迁移链到 0034；结果 **1071 passed、2 failed**。失败为 `tests/test_31_web_ui_console.py::test_real_console_create_confirm_debug_report`（测试页面未获得预期项目选择状态）和 `tests/test_36_agent_governance_details.py::test_skill_usage_read_model_counts_distinct_runs_and_limits_recent_tasks`（用量列表最新任务排序断言）。两者不是统一模型中心路径，本次保留为既有失败，没有扩大范围修复。开发库未重置。

## 浏览器验收与截图

用仅含合成 Text/ASR/DIARIZATION 模型记录的临时隔离 PostgreSQL 数据库启动 API 和前端，浏览器检查了 ASR 模型中心列表、资源新增表单、语言/热词/VAD/标点/时间戳生成控件以及安全说明；没有触发模型诊断，也没有真实厂商请求。初版曾将管理页面同时放在控制台；后续按产品范围调整为仅后台管理，旧地址改为跳转到后台。ASR 列表页面截图已随初版交付消息附出。浏览器工具提供内联截图，但当前本地截图落盘路径不可用，因此截图没有作为 PNG 文件纳入仓库。

**真实联调待验证**：目前没有厂商协议样例、真实凭据或项目出站授权；通用 JSON HTTP 适配器和合成测试不等于任一厂商已通过在线诊断。异步状态映射、签名/特殊上传、长音频约束、费用和模型效果需拿到具体协议后验收。

## 配置与启动

使用仓库已安装的依赖，连接正式开发库前先确认目标库。`backend/.env` 至少需配置 `DATABASE_URL` 与满足仓库规则的 `SECRET_KEY`。如单独配置 `MODEL_CONFIG_ENCRYPTION_KEY`，需沿用部署中已存在的密钥，保证旧密文可解密；未配置时平台由 `SECRET_KEY` 派生。密钥不能临时轮换，否则历史密文无法读取。

升级数据库（在 `backend` 目录）：

```bash
.venv/bin/python -m alembic upgrade head
```

分别启动 API、前端和 ASR 后台 worker：

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

前端默认在 `http://127.0.0.1:5173`，API 为 `http://127.0.0.1:8001`。平台管理员在管理后台选择项目范围并维护模型资源；ASR 新任务与说话人工作台的选择器只列出项目当前可用的类别模型。维护者应先按目标接口协议填写连接模板、响应映射、出站授权和参数定义，再通过合成响应或明确确认的诊断验证。通用 JSON 模板必须包含音频 URL 与参数方案占位符；没有鉴权的 endpoint 仍须满足平台出站目标授权。

## 回退方式

先暂停使用统一中心新增的资源和任务，备份数据库并导出新增模型资源、授权、默认项与参数方案。停止 worker，再回退应用版本。只有确认放弃 0034 后新增资源数据后，才运行：

```bash
cd /Users/a1/Desktop/ai-test-project/backend
.venv/bin/python -m alembic downgrade 0033
```

0034 downgrade 只删除统一模型中心新增表，旧 `ModelConfiguration`、ASR 连接/参数表和历史快照保留；但新建的模型中心专属资源、授权、诊断和任务槽位不一定有旧表副本，因此 downgrade 不是无损操作。应优先恢复数据库备份；不要用删除/重置数据库作为回退步骤。

## 未完成项

- 真实供应商协议、凭据、出站授权和实际线上请求待验证。当前通用适配器能力只覆盖明确实现的请求模板/JSON 响应映射。
- multipart、WebSocket、供应商签名、未注册协议及更细的服务端诊断报告未实现，不会显示为支持。
- 后端完整回归中上述两个既有失败仍待其各自任务处理。
- 浏览器截图已附于交付消息，未能作为本地 PNG 文件归档。
