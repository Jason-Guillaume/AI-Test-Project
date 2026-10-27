"""业务管理模块（business）。

提供统一业务模型：业务域（Business Domain）→ 业务流程（Business Flow）→ 业务动作
（Business Action）→ 业务绑定（Business Binding），供人工维护业务流程并关联 API 或 Web 用例。

API 绑定通过 api_id 引用接口管理（api_catalog）的 ApiInterface；Web 绑定引用同项目的
Web 用例。执行复用现有 API / Web 执行服务，业务模块不复制接口定义、用例或执行记录。

当前支持业务流程 CRUD、顺序执行、变量映射、VARIABLE / STATE 前置条件、状态配置，以及 API / Web 绑定执行。
BUSINESS / TEXT 前置条件只记录为人工核对项，不自动判定，也不阻断流程。

当前未接入：
- Agent / LangGraph / AI 自动识别与生成业务流程
- 移动端绑定执行
- 条件分支、并行、循环、DAG、BPMN、审批节点、等待与重试编排

数据 Factory 由测试数据模块单独提供，不属于业务流程执行器的能力。
"""
