# 全站 UI 审查报告

日期：2026-11-13
范围：`frontend/src/app/App.tsx` 中的前端路由、共享布局/状态组件，以及本次重点改造的模型、Agent、MCP、Skill、Tool 页面。

## 审查方式与覆盖范围

逐项核对了应用路由声明和对应页面模块，并检查共享导航、页面头部、分页/状态组件、详情抽屉、资源治理 API。浏览器路由/宽度巡检覆盖 63 条管理端与控制台页面路径及四种视口；11 个代表性业务页和五大资源入口另有四视口截图，资源中心另做关键交互验收。全站其他业务流程未宣称完成逐页操作验收。

路由范围：

- 认证与兜底：`/`、`/login`、`/register`、`/403`、`/404`、`*`。
- 管理端：`/admin/dashboard`、`users`、`organizations`、`projects`、`knowledge`、`model-configs`、`environments`、`agents`、`agent-runtime`、`mcp`、`skills`、`tools`、`recycle-bin`。
- 工作台与项目：`/console`、`projects`、`projects/:id`、`defects`、`api-catalog`、`business-management`、`test-asset`、`test-cases`、`test-suites`、`test-plans`、`execution-center`、`execution-history`、`test-reports`、`test-reports/:reportId`。
- 自动化及通知：`automation-projects`、`automation-runs`、`automation-history`、`automation-reports/:reportId`、`automation-integration`、`notification-channels`、`notifications`。
- 数据、Mock、安全与 Web UI：`test-data`、`mock-management`、`mock-management/services/:serviceId`、`mock-management/endpoints/:endpointId`、`mock-management/executions`、`security-testing`、`web-ui`、`web-ui-agent`。
- ASR：`asr/audio`、`asr/jobs`、`asr/jobs/:jobId`、`asr/runs/:runId`、`asr/runs/:runId/listen`、`asr/comparisons`、`asr/comparisons/:comparisonId`、`asr/experiments`、`asr/funasr`。
- 任务与个人空间：`tasks`、`tasks/inbox`、`tasks/templates`、`tasks/:taskId`、`agent`、`profile`。
- 兼容入口：`console/knowledge`、`console/model-center`、`console/asr/connections`。这些由现有路由重定向或显示权限提示，模型数据仍由统一模型中心维护。

## 发现与处理

| 严重程度 | 发现 | 处理 | 状态 |
|---|---|---|---|
| 阻断 | 从空库运行迁移时，初始迁移提前创建了 Organization 软删除列，`0084` 再新增列导致重复 | 让初始迁移继续保持历史基线，由 `0084` 引入这些列；从 base 到 head 重新迁移验证 | 已修复 |
| 高 | 工具目录标签行不换行，卡片在桌面宽度把文档推到视口之外 | 资源标签行启用换行，并把问题纳入 Playwright 的四视口宽度断言 | 已修复 |
| 高 | 知识库当前项目检索控件在移动端固有宽度超出视口 | 将检索行改为可收缩布局，纳入全路由四视口宽度断言 | 已修复 |
| 中 | 管理端/工作台侧栏缺少小屏收起入口，窄屏菜单会占用内容宽度 | 统一提供菜单按钮、遮罩和选中菜单后自动关闭；折叠状态沿用 Ant Design Layout | 已修复 |
| 中 | Agent 列表默认树形视图，卡片信息和搜索筛选入口不够直接 | 默认改为卡片，保留树/表格；新增搜索和卡片分页，保留批量删除及回收站 | 已修复 |
| 中 | 资源详情交互不统一，退出编辑时没有一致的未保存提示 | 扩展兼容既有 loading/error/empty 接口的 `DetailDrawer`，为 Agent、MCP、Tool 编辑提供明确的放弃确认 | 已修复 |
| 中 | Skill 管理缺少文件树与概览/编辑工作区 | 基于既有 `files_json`、版本与用量 API 建立工作区；文本文件可编辑，未知二进制明确提示不支持在线预览 | 已修复 |
| 低 | 用户页 Hook 依赖和自动化集成表单存在 lint 错误 | 使用稳定回调并移除无效临时字段赋值 | 已修复 |

## 浏览器验收边界

全站巡检通过登录后 SPA 导航访问 63 条已登记管理端/控制台页面路径（含 `/403`、`/404`），在 1440×900、1024×768、768×1024、390×844 下等待页面布局稳定并断言文档宽度不超过视口。11 个核心业务页（工作台、项目、接口、业务、测试资产、测试数据、执行、安全、报告、管理首页、用户管理）及五大资源入口另行逐页截图。资源中心还验证 Skill 新版本保存/恢复、Agent/MCP/Tool 未保存退出确认和 LLM 详情抽屉。路由宽度和截图不等同于各页完整 CRUD/执行流程验收。

## 已知能力边界

- 模型中心没有模型调用次数/费用汇总接口；页面不展示编造的使用统计。
- Tool 治理 API 没有每个工具的调用次数/运行历史接口；详情显示服务端提供的执行器状态、字段、约束和审计说明。
- MCP API 当前提供连接检查、发现结果、审批名单及 Agent 关联，没有每个 MCP 工具的调用历史/统计接口。
- 非 Skill 资源的直达详情 URL 不在当前路由契约内；详情仍在列表页 Drawer 中打开。
