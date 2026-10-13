"""业务管理模块（business）。

提供统一业务模型：业务域（Business Domain）→ 业务流程（Business Flow）→ 业务动作
（Business Action）→ 业务绑定（Business Binding），作为后续接口业务测试、Agent、
UI 自动化、移动端自动化的统一业务模型基础。

核心原则：业务层与具体执行方式解耦。binding_type 预留 API/WEB/MOBILE 三种绑定通道，
当前第一阶段只真正支持 API 绑定——通过 api_id 引用接口管理（api_catalog）的 ApiInterface，
不复制接口 Schema，接口在接口管理更新后仍引用同一个接口。

第一阶段只实现配置与持久化（CRUD + 步骤编排 + 变量映射 + 状态/规则配置 + 绑定失效识别），
不做测试执行。

未接入（明确标记，属后续阶段）：
- Agent / LangGraph / AI 自动识别与生成业务流程
- 测试点 / 测试用例生成与执行、Mock 执行
- Web Binding、Mobile Binding 的真正执行（UI 自动化 / Appium）
- 条件分支、并行、循环、DAG、BPMN、审批节点、Wait/Retry、数据 Factory
"""
