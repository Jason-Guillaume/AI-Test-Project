# 测试与验收报告

## 结果

| 检查 | 命令/覆盖 | 结果 |
|---|---|---|
| 前端类型检查 | `cd frontend && npm run typecheck` | 通过 |
| 前端 ESLint | `cd frontend && npm run lint` | 通过，`--max-warnings=0` |
| 前端单元测试 | `cd frontend && npm test` | 41 passed，0 failed |
| 前端生产构建 | `cd frontend && npm run build` | 通过，Vite 产物生成成功 |
| 后端迁移/初始化回归 | `backend/.venv/bin/python -m pytest tests/test_01_schema_and_seed.py -q` | 4 passed，1 条既有 Starlette/AnyIO 弃用告警 |
| Playwright 路由巡检 | `scripts/e2e_case_generation.sh e2e/all-routes-responsive.spec.ts` | 1 passed；63 条已登记页面路径 × 4 种视口 |
| Playwright 核心业务截图 | `scripts/e2e_case_generation.sh e2e/all-routes-responsive.spec.ts --grep 'representative business'` | 1 passed；11 个业务页 × 4 种视口，项目通过测试 API 创建 |
| Playwright 资源工作区 | `scripts/e2e_case_generation.sh e2e/skill-workspace.spec.ts` | 2 passed；隔离库从 base 迁移到 `0084` 并在退出时清理 |

## Playwright 覆盖

- Skill 创建后从 UI 编辑 `SKILL.md`、预览 Markdown、保存真实版本、添加文件、检查未知二进制提示，并从历史恢复成新版本；通过 API 验证版本和 `files_json`。
- 模型中心、Agent、MCP、Skill、Tool 五个资源页面分别在 1440×900、1024×768、768×1024、390×844 检查页面宽度并截全页图。
- 打开模型详情、Agent 详情、MCP 创建配置和 Tool 详情；Agent/MCP/Tool 有未保存修改时验证 Drawer 关闭提示。
- 分别选择“执行器未接入”和“执行器已接入”，校验 Tool 卡片实际筛选结果与卡片执行器状态一致。
- 登录后遍历 63 条管理端/控制台路由，在四种视口断言文档宽度不大于视口；该用例不声称覆盖这些页面的完整 CRUD、执行或错误/空状态流程。
- 对工作台、项目、接口目录、业务管理、测试资产、测试数据、执行中心、安全测试、测试报告、管理首页、用户管理各截四种视口页面图；测试 API 创建真实隔离项目并选择到控制台作用域，其余无种子业务资产的区域按真实空状态显示。
- E2E 数据库名以 `testplatform_e2e_` 开头，完全独立于开发库；最新运行已迁移到 `0084`，并由脚本清理。

## 截图

图片位于 `screenshots/`，共 68 张。下表每个资源均有四个目标视口截图：

| 页面 | 桌面 | 窄屏 | 平板竖屏 | 手机 |
|---|---|---|---|---|
| LLM | [1440×900](screenshots/llm-1440x900.png) | [1024×768](screenshots/llm-1024x768.png) | [768×1024](screenshots/llm-768x1024.png) | [390×844](screenshots/llm-390x844.png) |
| Agent | [1440×900](screenshots/agent-1440x900.png) | [1024×768](screenshots/agent-1024x768.png) | [768×1024](screenshots/agent-768x1024.png) | [390×844](screenshots/agent-390x844.png) |
| MCP | [1440×900](screenshots/mcp-1440x900.png) | [1024×768](screenshots/mcp-1024x768.png) | [768×1024](screenshots/mcp-768x1024.png) | [390×844](screenshots/mcp-390x844.png) |
| Skill | [1440×900](screenshots/skill-1440x900.png) | [1024×768](screenshots/skill-1024x768.png) | [768×1024](screenshots/skill-768x1024.png) | [390×844](screenshots/skill-390x844.png) |
| Tool | [1440×900](screenshots/tool-1440x900.png) | [1024×768](screenshots/tool-1024x768.png) | [768×1024](screenshots/tool-768x1024.png) | [390×844](screenshots/tool-390x844.png) |

Skill 文件工作区编辑后的页面截图另见 [桌面](screenshots/skill-workspace-1440x900.png)、[1024px](screenshots/skill-workspace-1024x768.png)、[平板](screenshots/skill-workspace-768x1024.png)、[手机](screenshots/skill-workspace-390x844.png)。

### 核心业务页面

| 页面 | 桌面 1440×900 | 1024×768 | 平板 768×1024 | 手机 390×844 |
|---|---|---|---|---|
| 工作台 | [截图](screenshots/console-home-1440x900.png) | [截图](screenshots/console-home-1024x768.png) | [截图](screenshots/console-home-768x1024.png) | [截图](screenshots/console-home-390x844.png) |
| 项目管理 | [截图](screenshots/projects-1440x900.png) | [截图](screenshots/projects-1024x768.png) | [截图](screenshots/projects-768x1024.png) | [截图](screenshots/projects-390x844.png) |
| 接口目录 | [截图](screenshots/api-catalog-1440x900.png) | [截图](screenshots/api-catalog-1024x768.png) | [截图](screenshots/api-catalog-768x1024.png) | [截图](screenshots/api-catalog-390x844.png) |
| 业务管理 | [截图](screenshots/business-management-1440x900.png) | [截图](screenshots/business-management-1024x768.png) | [截图](screenshots/business-management-768x1024.png) | [截图](screenshots/business-management-390x844.png) |
| 测试资产 | [截图](screenshots/test-assets-1440x900.png) | [截图](screenshots/test-assets-1024x768.png) | [截图](screenshots/test-assets-768x1024.png) | [截图](screenshots/test-assets-390x844.png) |
| 测试数据 | [截图](screenshots/test-data-1440x900.png) | [截图](screenshots/test-data-1024x768.png) | [截图](screenshots/test-data-768x1024.png) | [截图](screenshots/test-data-390x844.png) |
| 执行中心 | [截图](screenshots/execution-center-1440x900.png) | [截图](screenshots/execution-center-1024x768.png) | [截图](screenshots/execution-center-768x1024.png) | [截图](screenshots/execution-center-390x844.png) |
| 安全测试 | [截图](screenshots/security-testing-1440x900.png) | [截图](screenshots/security-testing-1024x768.png) | [截图](screenshots/security-testing-768x1024.png) | [截图](screenshots/security-testing-390x844.png) |
| 测试报告 | [截图](screenshots/test-reports-1440x900.png) | [截图](screenshots/test-reports-1024x768.png) | [截图](screenshots/test-reports-768x1024.png) | [截图](screenshots/test-reports-390x844.png) |
| 管理首页 | [截图](screenshots/admin-dashboard-1440x900.png) | [截图](screenshots/admin-dashboard-1024x768.png) | [截图](screenshots/admin-dashboard-768x1024.png) | [截图](screenshots/admin-dashboard-390x844.png) |
| 用户管理 | [截图](screenshots/admin-users-1440x900.png) | [截图](screenshots/admin-users-1024x768.png) | [截图](screenshots/admin-users-768x1024.png) | [截图](screenshots/admin-users-390x844.png) |

## 失败发现与修复

- 第一次从空库迁移时发现 `0001` 和 `0084` 对 Organization 生命周期列重复创建；修复初始基线后全量迁移到 `0084` 成功，schema/seed 回归 4 项通过。
- 四视口资源页检查发现 Tool 卡片标签导致 1440px 横向溢出；标签允许换行后，全套资源页宽度断言通过。
- 最终 Playwright 路由巡检、11 页核心截图、Skill 工作区和资源页四项验收均通过。开发过程中发现并修复 Tool 卡片、知识库检索区的移动/窄屏溢出。测试选择器曾出现不稳定匹配，现使用 Drawer close 图标和确认弹窗操作；它不是产品功能失败。

## 验收限制

此报告只将实际执行的命令和浏览器路径记为通过。所有登记的管理端/控制台页面路径完成了四视口可达性与横向宽度巡检；除资源中心重点流程外，其他业务页没有全部逐页留存四视口截图，也没有完成完整 API 业务流程回归，后续仍需按模块验收。
