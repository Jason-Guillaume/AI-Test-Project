"""bootstrap 包：应用装配相关模块。

目前只包含路由总装（routes.py），未来可以扩展为启动钩子、依赖预热等；
主入口 `app.main:create_app` 会把这些装配组合成最终可用的 FastAPI 实例。
"""
