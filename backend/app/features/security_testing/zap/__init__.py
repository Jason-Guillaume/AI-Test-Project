"""OWASP ZAP 安全扫描集成（Security Testing Phase 2）。

在 Phase 1 的「接口安全变异」之外增加真实扫描器能力：被动扫描、Client Spider
Web 爬取、受控主动扫描，以及认证扫描（JWT / Header / 浏览器登录态）。

分层约定：
    transport.py   唯一持有 ZAP API Key 的一层；上层看不到明文
    connector.py   ZAP REST API ↔ 平台契约；范围限制在此落地
    contracts.py   平台侧数据类与枚举（业务层唯一依赖）
    scope_guard.py 目标合法性与 SSRF 守卫（DNS / 重定向 / 允许主机）
    openapi_export.py  ApiInterface + ApiParameter → OpenAPI 3（剥离外部 servers）
    auth_check.py  登录态验证（不认 HTTP 200）
    normalizer.py  ZAP 告警归一化 + 指纹 + 脱敏
    models/        SecurityScanTarget / Profile / AuthProfile / Job / Event
    router.py      路由（不拼 ZAP 请求，只调 service）
    services/      业务服务
    worker.py      DB 支撑的异步扫描执行器
    mock.py        进程内 ZAP 模拟器（单元测试用，不发任何出站请求）

边界（与 Phase 1 一致）：
- Finding 复用 security_finding，不建第二套结果体系；指纹加 ``zap|`` 命名空间。
- 不建第二套 TestRun / Agent / Report / 权限系统。
- 凭据（Bearer Token / Cookie / ZAP API Key）只以参数在进程内传递，绝不入库、
  不进日志、不进事件表、不进 Agent Prompt。
- 范围限制在所有发往 ZAP 的请求前生效，不只在前端做一次确认。
"""
