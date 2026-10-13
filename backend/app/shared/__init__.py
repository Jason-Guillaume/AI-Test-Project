"""跨模块共享基础设施：配置、数据库、认证依赖、分页、错误。

本包提供权限与认证（auth / roles / dependencies）、错误信封（errors）、分页
（pagination）、限流（rate_limit）、请求上下文（request_context）、密码哈希
（passwords）与通知写入（notify）等公共能力，被 app/features 下各业务模块
以及 app/main.py 的启动装配统一导入使用；业务模块不应直接依赖其他业务模块。

app/api、app/services 等 feature 模块统一从这里取用公共能力，避免在每个业务模块里
重复装配数据库会话、JWT 校验、分页参数、错误信封与角色判定：
- config：全局配置（环境变量 / .env）与运行时密钥读取
- database：SQLAlchemy engine、SessionLocal、请求级会话依赖
- auth / passwords：JWT 签发与校验、令牌撤销位、密码哈希
- dependencies：可复用的 Depends 组合（DB / Current / 管理员门槛）
- roles：平台、组织、项目三级角色判定与可见性边界
- errors：统一错误信封与全局异常处理器
- pagination：统一分页参数与列表响应结构
- rate_limit / request_context / notify：登录注册限流、请求链路 ID、通知写入
"""
