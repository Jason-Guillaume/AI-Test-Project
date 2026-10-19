"""Mock Management（Phase 1）：接口 Mock 与依赖异常模拟。

Mock 解决「测试执行期间依赖服务应如何表现」，与 Data Factory（测试前造数）严格分离
（§一）。本 feature 只控制依赖行为，不造数、不执行被测用例、不重新实现已有执行体系。

复用当前统一架构（§禁止重新实现）：
- 模板解析复用 test_data.runtime.variable_resolver（扩展 request / runtime 命名空间，§十二）
- 敏感脱敏复用 business.executors.sensitive.SensitiveDataMasker（§五十）
- 项目权限复用 shared.roles 的 viewer/member/editor 口径（§三十四）
- 用例执行复用 test_management.executors.test_case_executor + run_service（§二十二/§二十七）

管理面（router.py，需平台 JWT）与执行面（runtime_router.py，X-Mock-Token 鉴权）分离（§十四）。
"""
