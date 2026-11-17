# 修复记录

## 数据库迁移

- `backend/alembic/versions/0084_organization_recycle_bin.py`：对 `organization` 四个生命周期列逐项检查并补齐；独立检查 `deleted_by → user.id` 外键；SQLite 使用 batch alter 补外键。downgrade 保留 nullable 字段、约束及历史软删除值，避免误删来源不明的数据结构。
- 新增 `backend/tests/test_57_organization_recycle_bin_migration.py`：覆盖 SQLite 字段组合、已有/缺失外键、PostgreSQL 空字段补齐、部分历史列、重复 upgrade、数据保留和安全 downgrade。
- `backend/app/platform/model_configuration/tests/test_model_center.py`：补模型诊断项目权限、ASR/说话人音频归属和明确计费确认的服务层测试；测试夹具显式注册 API catalog 外键依赖。

## 模型中心与卡片操作

- `frontend/src/pages/console/ModelCenterPage.tsx`：诊断表单提供项目选择，只列出当前用户有编辑权限的项目；音频查询按所选项目隔离并在项目切换时清除旧项目缓存；请求使用表单里的项目 ID。保留计费警告、用户确认、轮询与结果脱敏，并用同步 in-flight 标记阻止重复提交。
- 详情抽屉只保存模型 ID，从最新 React Query 列表派生详情；查询刷新时显示加载态，类别/项目上下文变化或资源消失时关闭抽屉。
- `frontend/src/pages/admin/AgentGovernance/AgentPane.tsx` 与模型资源卡移除了整卡按钮语义，保留显式的详情、编辑、诊断、历史和删除按钮，避免内部键盘操作触发外层详情。
- `frontend/src/app/layouts/ConsoleLayout.tsx` 补齐 ASR 音频、运行工作台、FunASR 等路由面包屑标题。

## 质量门禁与 E2E

- `frontend/e2e/all-routes-responsive.spec.ts` 为已登记路由增加标题/核心内容验收，检查 pageerror、console.error、API 网络错误和系统级响应；403/404 作为可识别的权限或资源业务结果单独记录。继续检查横向溢出和主要操作按钮遮挡，覆盖 1440×900、1024×768、768×1024、390×844。
- 新增 `frontend/e2e/model-center.spec.ts`：通过真实 API 创建隔离项目与合成模型，覆盖详情、连接修订、参数方案、默认策略和诊断同意步骤；浏览器流程不提交真实模型调用。
- `frontend/e2e/skill-workspace.spec.ts` 去除固定等待，验收截图输出改到交付目录。
- 新增 `.github/workflows/quality.yml`：提交级前端、后端迁移/单测和隔离 Playwright 工作流。
- `docs/second-round-quality-fix/screenshots/README.md` 记录截图生成方式与本次阻断状态。

## API 与计费边界

没有修改模型诊断请求/响应合同。后端仍对项目编辑权限、模型在项目中的可用性、音频所属项目和 `confirm_model_call=true` 做校验。单测只验证任务排队和拒绝边界，没有请求外部模型服务。
