"""接口管理（API Catalog）模块。

Phase 范围（**已接入**）：
- 模块树（最多两级，自动维护「未分类」）与接口的 CRUD
- 请求参数（PATH/QUERY/HEADER/COOKIE/BODY：JSON/Form/Multipart/Raw）/ 响应结构 / 接口关联
- 接口调试：选环境发真实请求，强制校验项目出站目标白名单（仅平台管理员）
- 导入：Curl 单接口导入、OpenAPI 3.x（JSON/YAML）/ Swagger 2.0 批量导入
- 统一 ModuleResolver、Internal API Schema、去重（project_id+method+path）、变更检测与变更记录、导入记录

所有外部格式先转换成统一 Internal API Schema；后续 Agent 只依赖 Internal Schema。

权限：读 viewer+，写 member+，调试 require platform admin；越权按 404 隐藏存在性。

未接入（**属后续阶段**，不做假实现）：
- AI 测试点 / AI 测试用例 / LangGraph 编排 / 业务场景
- 自动 Mock / 安全测试 / 性能测试
- 接口关联的自动分析（目前人工维护，后续 Agent 自动推导）
"""
