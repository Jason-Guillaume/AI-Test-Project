"""测试开发平台后端。

顶层包：作为 `app.main`、`app.features.*`、`app.models`、`app.shared`
的共同父包，负责统一命名空间；对外暴露版本号供 `GET /api/v1/meta` 与运维侧识别使用。
"""

# 应用版本号：部署后前端与运维通过 GET /api/v1/meta 与日志启动行拿到该值，改动需同步升版
__version__ = "1.0.0"
