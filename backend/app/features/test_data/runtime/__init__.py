"""Data Factory 运行时包。

分层约定（模块之间单向依赖，避免循环导入）：

- ``variable_resolver``：模板求值，不做 I/O（唯一副作用是 Faker 的随机函数）。
  用例执行器也共用它，保证「用例里的 ${env.x}」和「Fixture 步骤里的 ${env.x}」
  取值口径一致。
- ``fixture_resolver``：Fixture 可见性判定与依赖展开（依赖先于自己）。
- ``data_factory``：编排 + 写执行记录 + 脱敏 + 计时 + 状态流转。
- ``cleanup_runner``：按 cleanup_handle 与 CLEANUP 步骤执行清理。

Provider 在 ``providers`` 包里，只返回 ``ProviderResult``，自己不写
``provider_execution``。
"""

__all__ = ["cleanup_runner", "data_factory", "fixture_resolver", "variable_resolver"]
