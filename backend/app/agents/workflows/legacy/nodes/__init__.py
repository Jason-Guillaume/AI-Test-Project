"""Agent 工作流节点集合。

每个节点文件导出一个 `xxx_node(ctx, state) -> dict` 函数，由 graph.py 通过
`functools.partial(node_fn, ctx)` 绑定上下文后注册为 langgraph 节点。
"""
