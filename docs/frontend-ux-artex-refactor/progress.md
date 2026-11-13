# 前端体验重构进度

日期：2026-11-13

## 当前状态

- 当前分支：`feature/frontend-ux-artex`，基于本地缓存 main 快照 `e3747c0`；未提交到 main。
- 实现提交：`e41e062b7761b76c123e3a3af9a68f10c6627d33`（`feat: redesign agent governance and responsive UX`）。
- 原始 `codex/jenkins-provider` 工作区的已有修改保留在独立 worktree `/private/tmp/ai-test-project-jenkins`；本 worktree 的 `.idea/` 与 `docs/platform-fixes-2026-11-12.md` 未纳入本次修改。
- 资源目录完成第一轮：LLM、Agent、MCP、Skill、Tool；共享侧栏响应式、详情 Drawer 兼容扩展。
- 后端初始迁移重复 Organization 生命周期字段的问题已修复并验证到 Alembic `0084`。
- 24 张截图已写入 `screenshots/`。
- 六份交付报告已建立。
- 全站路由巡检已通过：63 条管理端/控制台页面路径在四视口无页面级横向溢出；Knowledge 检索栏移动端超宽问题已修复。

## 最新验证

- `frontend`: typecheck、lint、41 个单元测试和 build 通过。
- 后端 `tests/test_01_schema_and_seed.py`: 4 passed、1 个既有弃用告警。
- Playwright 最终运行：路由巡检 1 passed，Skill 工作区 1 passed，五个资源页面 1 passed；Tool 执行器筛选另做定向浏览器复验并通过。四视口宽度、Skill 版本保存/恢复、详情 Drawer 和未保存关闭确认均通过；隔离数据库已删除。

## 后续范围

用户原需求还要求项目、接口、业务管理、测试资产、测试数据、自动化执行、安全测试、报告、通知和个人中心等所有页面逐页四视口截图和完整流程验收。已完成全部登记路由的可达性/页面宽度巡检，但这些模块没有逐页留图或完成业务流程测试；`01`、`05`、`06` 报告已明确此边界。模型调用次数、Tool/MCP 运行历史也缺少后端接口，未伪造数据。

## 工作区保护

- 用户已有未提交文件没有加入本次提交。
- 本地 remote refs 尚未刷新；`git fetch` 因 `.git/FETCH_HEAD` 权限拒绝失败，分支比较使用本地缓存 refs。
