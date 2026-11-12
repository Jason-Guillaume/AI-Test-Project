"""测试管理执行引擎。

- assertion_engine：纯逻辑断言引擎（JSONPath / StatusCode / Header / ResponseTime / Contains）
- test_case_executor：按 target_type 路由（API→ApiRequestExecutor，BUSINESS_FLOW→execute_flow，
  BUSINESS_ACTION→绑定+映射+ApiRequestExecutor），复用业务执行器与脱敏器，禁止重新实现 HTTP/业务流执行。
"""
