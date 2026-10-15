"""测试数据中心服务层（feature-local）。

权限口径与 test_management / business 一致：
- 读：项目 viewer+，不可见与不存在共用 404（隐藏存在性）；
- 写：项目 member+，不足 403；
- 被测库连接与数据库策略：平台管理员（Environment 本身是平台级危险配置）。

service owns commit。
"""
