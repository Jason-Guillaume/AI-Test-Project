"""Security Testing Phase 2 —— ZAP 集成的业务服务层。

分层约定（与仓库其它 feature 一致）：
- Router 只做参数解析与响应组装，业务判断全部落在本目录下的 service 模块；
- 执行层（worker / orchestrator）与 HTTP 请求解耦：请求只登记任务，扫描在后台跑。

模块职责：
- ``_access``：项目角色校验与跨资源 404 的集中实现（红线 1）。
- ``target_service`` / ``profile_service`` / ``auth_profile_service``：三类配置的 CRUD。
- ``job_service``：扫描任务的创建、取消、计划、查询与报告。
"""
