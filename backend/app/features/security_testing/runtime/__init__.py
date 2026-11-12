"""Security Testing 运行时（变异引擎）。

纯函数目录：本包里的模块不做 HTTP、不查库、不 ``eval``（开发计划 §6.3）。
唯一的出站调用发生在 Phase E 的 ``runner.py``。

    types.py           数据结构与引擎哨兵异常
    schema_reader.py   ApiParameter + ApiRequestBody.schema_json → FieldSpec
    candidate_resolver.py  从 Fixture 输出取「另一个用户 / 另一个项目的资源」
    operators.py       算子注册表（一个 mutation_type 一个纯函数）
    mutation_engine.py SecurityMutationEngine.apply
    replay.py          有上限的重复执行（次数 2～3，间隔 0～5000ms）
    business_plan.py   重放/重复提交/业务状态/跳步的计划项生成
    trace.py           trace 生成与脱敏
    assertion.py       安全期望判定
    severity.py        严重级别规则表
    baseline.py        生产环境闸门 + BaselineRequest 组装（纯函数）
    runner.py          唯一的例外模块：查库、写 execution、调 ApiRequestExecutor
"""
