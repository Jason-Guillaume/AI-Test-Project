# 前端开发约定

- 在 frontend 目录使用 npm，按 `package-lock.json` 安装依赖（`npm ci`）。页面入口、业务功能和跨页面组合组件分别参考 `src/pages/`、`src/features/`、`src/widgets/` 的同类实现。
- 业务请求复用 `src/shared/api/client.ts` 的 Axios 客户端。改动接口时同步核对后端 schema、调用方和分页结构。使用 React Query 的功能应沿用同域查询键，写入成功后更新或失效受影响的列表和详情。
- 保持现有中文界面用语，复用 `src/shared/ui/` 的表格、筛选栏、状态和抽屉组件。修改公共组件前检查调用方，验证键盘操作、错误反馈以及窄屏布局。
- 可选字段、空列表和数值 0 按各自业务含义展示。异步表单保留提交中、失败和成功反馈，避免重复提交。跨页面的格式化规则先查 `src/shared/lib/`。
- 代码改动运行 `npm run typecheck`、`npm run lint` 和 `npm test`。影响构建或懒加载时补跑 `npm run build`。页面交互改动选取 `e2e/` 中对应的 Playwright 场景，按项目的隔离环境配置运行。
