"""Agent Tool 层（§32）：对现有业务能力的薄封装。

四个 tool 模块都是「携带 project_id + user 的读 / 写入口」，复用既有 service 与 ORM，
Agent 的 LLM 输出经 Tool 落库，**不**由 LLM 直接执行代码或 SQL（§19）。

- `api_catalog_tool`：接口检索 / 详情（只读）。
- `business_tool`：业务流程 / 动作 / 绑定 / 规则（只读）。
- `fixture_tool`：可用 Fixture 清单（只读，只给 key 与输出契约名，无 Provider 配置）。
- `test_asset_tool`：策略 / 测试点 / 用例的读取、去重与保存（source_type=AI）。
- `execution_tool`：临时计划 + 套件的执行编排与执行结果读取。
- `security_tool`：安全策略 / 计划预览与确认 / Finding / 执行结果（Phase F，只读为主）。
- `zap_scan_tool`：ZAP 扫描目标 / 策略 / 计划预览（Phase 2，只读）；创建任务必须
  带 `human_approved=True`，该参数只有人工 `confirm_security_scan` 动作能置真（§二十三）。

跨项目访问统一 404（§33）；写操作需 project member（不足 403）。
"""
