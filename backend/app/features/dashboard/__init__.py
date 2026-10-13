"""看板模块：工作台与平台概览统计。

对外暴露三个子模块：
- router  : HTTP 路由（/api/v1/dashboard/*），负责权限判定与依赖注入
- service : 业务逻辑与降级判断，负责生成「未接入」hint 与 visibility 边界
- schemas : Pydantic 契约，响应体始终带 scope 说明当前统计口径

统计口径全部限定为「当前用户可见范围」，避免把全局数字误当个人指标展示。
"""
