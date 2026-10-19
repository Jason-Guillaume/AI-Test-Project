"""安全测试（Security Testing Phase 1）。

在现有执行体系上增加接口安全变异：从一条正常请求出发，按策略生成认证、越权、
参数、重放与业务状态变异，执行后给出可解释的疑似问题。

边界（与功能用例严格分离）：
- 安全用例本体仍是 ``test_case``（case_type='SECURITY'），本包只存扩展数据，
  因此它天然能进入套件、计划、TestRun 与报告。
- 本包只负责「改请求」与「解释结果」。HTTP 仍走 ``ApiRequestExecutor``，
  TestRun 仍走 ``RunService``，Mock 与 Fixture 仍由原生命周期包裹。
- 引擎不发 HTTP、不建第二套 TestRun、不自动建缺陷、不签发 Token、不改平台用户角色。
- 生产环境硬拒绝，出站目标已标记为生产的地址同样拒绝；预留攻击类别无法执行。
"""
