"""首期支持的工作流模板和平台内置工具白名单。"""

WORKFLOW_TEMPLATES = {
    "api_test": {"label": "接口测试", "description": "接口理解、用例生成、执行与结果分析"},
    "web_ui": {"label": "Web UI 测试", "description": "页面观察、步骤规划与人工确认执行"},
    "security": {"label": "安全测试", "description": "安全测试计划、风险确认与结果分析"},
    "reporting": {"label": "测试报告", "description": "汇总执行结果并生成测试报告"},
}

# 每个 key 必须对应仓库内受控实现；此目录不支持从界面上传 Python/SQL/命令代码。
BUILTIN_TOOLS = [
    {"key": "api_catalog.search_api", "name": "查询接口目录", "category": "接口测试", "risk": "只读", "description": "按项目检索接口定义与请求结构。"},
    {"key": "business.list_flows", "name": "查询业务流程", "category": "业务管理", "risk": "只读", "description": "读取项目内业务流程、规则与接口绑定。"},
    {"key": "test_asset.get_existing_cases", "name": "读取测试资产", "category": "测试资产", "risk": "只读", "description": "读取项目已有测试点、用例及策略。"},
    {"key": "test_asset.save_cases", "name": "保存测试用例", "category": "测试资产", "risk": "写入", "description": "将经校验的生成结果写入项目测试资产。"},
    {"key": "execution.create_test_run", "name": "创建用例执行", "category": "测试执行", "risk": "执行", "description": "按项目权限创建并执行已确认的测试用例。"},
    {"key": "execution.get_test_run", "name": "查询执行结果", "category": "测试执行", "risk": "只读", "description": "读取用例执行状态与断言结果。"},
    {"key": "report.generate", "name": "生成测试报告", "category": "测试报告", "risk": "写入", "description": "基于真实 TestRun 统计并生成正式报告。"},
    {"key": "report.review", "name": "审阅测试结果", "category": "测试报告", "risk": "只读", "description": "核验执行覆盖、报告统计与验收条件。"},
    {"key": "security.preview_plan", "name": "预览安全计划", "category": "安全测试", "risk": "写入", "description": "生成待人工确认的结构化安全计划快照，不发出测试请求。"},
    {"key": "security.list_strategies", "name": "读取安全策略目录", "category": "安全测试", "risk": "只读", "description": "读取当前项目已启用的策略和规则摘要，不暴露变异配置。"},
    {"key": "security.read_api_context", "name": "读取 API 安全上下文", "category": "安全测试", "risk": "只读", "description": "读取登记 API 的方法、路径、认证类型和功能基线数量，不读取请求值或响应正文。"},
    {"key": "security.read_findings", "name": "读取历史疑似问题", "category": "安全测试", "risk": "只读", "description": "读取所选 API 未关闭 Finding 的脱敏摘要，不读取证据或响应正文。"},
    {"key": "security.inspect_web_session", "name": "检查受控 Web 页面", "category": "安全测试", "risk": "只读", "description": "只检查用户已打开的项目受控浏览器当前页面的响应头与有限 DOM 信号，不导航或点击。"},
    {"key": "security.confirm_plan", "name": "确认安全计划", "category": "安全测试", "risk": "高风险", "description": "仅在显式风险确认后创建安全测试任务。"},
    {"key": "security.execute_cases", "name": "执行安全用例", "category": "安全测试", "risk": "执行", "description": "仅执行已登记接口、已确认策略和用户批准的安全变异用例。"},
    {"key": "web_ui.generate_draft", "name": "生成 Web 用例草稿", "category": "Web UI", "risk": "写入", "description": "生成需用户确认的页面用例草稿。"},
]

TOOL_BY_KEY = {item["key"]: item for item in BUILTIN_TOOLS}
