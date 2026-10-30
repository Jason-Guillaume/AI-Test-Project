# Agent 治理与任务运行

Agent、Skill、MCP 与内置工具由平台管理员在「Agent 治理中心」统一管理。配置只引用服务端注册的能力，不接收 Python、Shell、SQL 或 LangGraph 源码。

## 配置顺序

1. 在 Skill 页维护 Markdown 指令与知识，先启用需要复用的 Skill。
2. 在工具页查看服务端内置工具；这些能力只能通过仓库中的白名单实现。
3. 如需远端能力，在 MCP 页登记 Streamable HTTP 地址，连接并发现工具，再由管理员审批。
4. 创建叶子 Agent，设置工作流、模型、指令和 Skill。叶子 Agent 不能再包含子 Agent。
5. 创建父 Agent 时按顺序选择最多 8 个已启用叶子 Agent。它们会在任务 Planner 前作为 LangGraph 分析节点依次运行，输出仅供 Planner 参考。
6. 父 Agent 可关联内置工具，以及获批且 MCP annotations 明确标记 `readOnlyHint: true` 的远端工具。启用时后端会复核依赖状态。
7. 在项目任务创建页选择父 Agent。任务运行会冻结父子 Agent、Skill 版本与 MCP 工具白名单；模型授权仍按当前组织权限复核。

## 运行边界

- 子 Agent 只生成分析建议，没有工具、写入、审批或执行权限。测试执行、安全变异和报告继续由平台固定节点完成。
- 只有获批的只读 MCP 工具能在 Planner 规划期间被模型调用；写入、高风险或未声明只读的远端工具不会自动执行。
- MCP 工具调用的参数与结果只保留在服务端运行回执中；任务详情仅向项目成员显示工具名、状态、时间和错误码。
- MCP 服务停用、取消审批、断开连接或不再声明只读后，运行时会拒绝新的调用。Bearer Token 加密保存，API 和任务详情不返回明文。
- 子 Agent 最多一层，最多 8 个；不支持任意图代码、循环图或动态脚本。新增节点类型需通过代码评审后加入服务端注册表。

## 数据库

截至 2026-10-28，本地 Alembic 迁移链实测 head 为 `0029_agent_tool_overrides`。共享目录迁移只调整 Python 模型归属，没有新增结构迁移。部署前仍应按仓库流程执行 `alembic upgrade head`；目录迁移本身不自动启动或修改运行中的后端服务。


## 综合拆分后的服务归属（2026-10-29）

Agent 的定义/修订、工具授权、Skill/MCP 引用分别由 `app/agents/services/definition_service.py`、`tool_governance_service.py`、`reference_service.py` 持有；依赖校验归 `link_validation.py`。治理路由继续调用 Agent 上层协调入口，保留正在引用 Skill/MCP 的删除与恢复保护。会话公开门面委托 session_access/message_store/proposal_service/session_state/session_turn/session_response；工作区装配为 `workspace_response.build_workspace`，任务内 Web 服务不再引用 Agent Router 私有函数。Legacy 图边与人工暂停点没有重写。统一目录与验证见 [后端综合交付记录](agent-cluster-refactor/backend-comprehensive-delivery.md)。
