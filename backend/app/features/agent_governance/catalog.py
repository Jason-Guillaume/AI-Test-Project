"""首期支持的工作流模板和平台内置工具白名单。"""

WORKFLOW_TEMPLATES = {
    "api_test": {"label": "接口测试", "description": "接口理解、用例生成、执行与结果分析"},
    "web_ui": {"label": "Web UI 测试", "description": "页面观察、步骤规划与人工确认执行"},
    "security": {"label": "安全测试", "description": "安全测试计划、风险确认与结果分析"},
    "reporting": {"label": "测试报告", "description": "汇总执行结果并生成测试报告"},
}

# 平台工具目录；已接入项映射到仓库内受控实现，目录不支持上传 Python/SQL/命令代码。
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

# 内置工具的详情来自当前固定工作流，而不是动态执行器。输入列说明运行时上下文来源，
# 不能通过管理页改成任意函数参数。只有 description 与安全授权允许管理员覆写。
TOOL_RUNTIME_DETAILS = {
    "api_catalog.search_api": {
        "status": "active", "status_label": "已接入任务 Planner", "runtime_name": "api-catalog.search", "runtime_role": "Planner",
        "input_context": [
            {"name": "project_id", "source": "任务上下文", "description": "由当前任务项目自动注入。"},
            {"name": "api_ids", "source": "已选测试资产", "description": "从当前任务选择的用例关联接口中提取。"},
        ],
        "output": "项目内接口名称、方法、路径及已登记请求结构，作为方案规划上下文。",
        "constraints": ["仅访问当前项目接口目录。", "停用或不属于当前项目的接口不会进入方案上下文。"],
        "audit": "受任务运行与 Planner 工具白名单控制；接口来源记录在本次方案快照中。",
    },
    "business.list_flows": {
        "status": "catalog_only", "status_label": "当前执行器未接入", "runtime_name": None, "runtime_role": "未绑定固定工作流节点",
        "input_context": [], "output": "登记描述为项目业务流程、规则与接口绑定。",
        "constraints": ["当前固定任务 Worker 没有对应的业务流程调用节点。", "Agent 绑定不会使此工具自动执行。"],
        "audit": "当前没有对应的任务工具调用记录。",
    },
    "test_asset.get_existing_cases": {
        "status": "active", "status_label": "已接入任务 Planner", "runtime_name": "test-asset.read", "runtime_role": "Planner",
        "input_context": [
            {"name": "project_id", "source": "任务上下文", "description": "由当前任务项目自动注入。"},
            {"name": "case_ids", "source": "任务选择", "description": "只读取当前任务已选择且仍属于本项目的用例。"},
        ],
        "output": "所选测试用例名称、说明、目标类型和关联接口摘要。",
        "constraints": ["只读取本次任务选择的资产。", "不会跨项目搜索或修改用例。"],
        "audit": "读取范围随任务方案快照保留。",
    },
    "test_asset.save_cases": {
        "status": "catalog_only", "status_label": "当前执行器未接入", "runtime_name": None, "runtime_role": "未绑定固定工作流节点",
        "input_context": [], "output": "登记描述为经校验后保存测试资产。",
        "constraints": ["当前固定任务 Worker 没有对应的用例写入节点。", "Agent 绑定不会触发资产写入。"],
        "audit": "当前没有对应的任务工具调用记录。",
    },
    "execution.create_test_run": {
        "status": "active", "status_label": "已接入 API / Web 执行 Worker", "runtime_name": "test-run.create / web-test-run.create", "runtime_role": "执行 Worker",
        "input_context": [
            {"name": "case_ids", "source": "人工批准的方案", "description": "执行范围必须来自当前版本已批准方案。"},
            {"name": "environment_id", "source": "项目环境绑定", "description": "由方案选择并重新校验项目环境。"},
        ],
        "output": "真实 TestRun 标识、执行状态、断言结果与可回链的执行记录。",
        "constraints": ["只执行已批准、仍启用且属于当前项目的用例。", "写操作前再次检查项目权限、环境关联和任务状态。"],
        "audit": "写入 TaskToolInvocation，并关联 TestRun 与当前 TaskRun。",
    },
    "execution.get_test_run": {
        "status": "active", "status_label": "已接入报告与审阅节点", "runtime_name": "test-run.read", "runtime_role": "报告 Agent / Reviewer",
        "input_context": [
            {"name": "test_run_id", "source": "当前任务执行结果", "description": "由依赖的执行 Worker 结果自动传入。"},
        ],
        "output": "TestRun 状态、统计、断言结果及其与批准范围的对应信息。",
        "constraints": ["只读取当前任务关联的执行记录。", "不会修改 TestRun 或断言结果。"],
        "audit": "在任务审阅和报告流程中留有 TaskRun 与 TestRun 关联记录。",
    },
    "report.generate": {
        "status": "active", "status_label": "已接入报告 Agent", "runtime_name": "report.generate", "runtime_role": "REPORT_AGENT",
        "input_context": [
            {"name": "test_run_id", "source": "当前任务执行结果", "description": "由已成功完成的执行 Worker 传入。"},
        ],
        "output": "基于真实 TestRun 统计创建的正式报告及其报告标识。",
        "constraints": ["必须存在当前任务关联的 TestRun。", "报告统计由平台服务计算，模型仅补充摘要。"],
        "audit": "创建 TaskToolInvocation，并写入 business.report.created 任务事件。",
    },
    "report.review": {
        "status": "active", "status_label": "已接入 Reviewer", "runtime_name": "report.review", "runtime_role": "REVIEWER",
        "input_context": [
            {"name": "test_run_id", "source": "当前任务执行结果", "description": "由依赖的报告流程传入。"},
            {"name": "approved_case_ids", "source": "已批准方案", "description": "用于核对报告统计是否超出批准范围。"},
        ],
        "output": "报告统计、执行范围、验收条件与正式 TestRun 事实之间的核验结论。",
        "constraints": ["结论必须由正式执行与报告记录支撑。", "Reviewer 不会补造测试结果或修改报告。"],
        "audit": "审阅结论写入 TaskRun 消息和事件记录。",
    },
    "security.preview_plan": {
        "status": "active", "status_label": "已接入安全 Planner / Worker", "runtime_name": "security-plan.preview", "runtime_role": "安全 Planner",
        "input_context": [
            {"name": "api_ids", "source": "用户创建任务时选择", "description": "最多 10 个仍启用且属于当前项目的 API。"},
            {"name": "strategy_ids", "source": "用户创建任务时选择", "description": "必须是当前项目启用的安全策略。"},
        ],
        "output": "结构化安全计划快照、风险提示和待人工确认的计划版本。",
        "constraints": ["预览阶段不发出测试请求。", "执行前必须由用户确认计划和风险。"],
        "audit": "创建 TaskToolInvocation，记录预览输入、结果及计划版本。",
    },
    "security.list_strategies": {
        "status": "active", "status_label": "已接入安全 Planner", "runtime_name": "security-strategy.read", "runtime_role": "安全 Planner",
        "input_context": [
            {"name": "project_id", "source": "任务上下文", "description": "只读取当前项目启用策略。"},
            {"name": "strategy_ids", "source": "用户创建任务时选择", "description": "结果进一步按本次任务所选策略过滤。"},
        ],
        "output": "策略名称和规则摘要，不包含变异配置。",
        "constraints": ["只读当前项目已启用策略。", "不暴露可执行载荷或变异配置。"],
        "audit": "通过安全只读工具写入 TaskToolInvocation。",
    },
    "security.read_api_context": {
        "status": "active", "status_label": "已接入安全 Planner", "runtime_name": "security-context.read", "runtime_role": "安全 Planner",
        "input_context": [
            {"name": "api_ids", "source": "安全评估选择", "description": "只包含本次任务选定的项目内 API。"},
        ],
        "output": "API 方法、路径、认证类型和功能基线数量。",
        "constraints": ["不读取请求值、响应正文或凭据。", "API 必须仍启用并属于当前项目。"],
        "audit": "通过安全只读工具写入 TaskToolInvocation。",
    },
    "security.read_findings": {
        "status": "active", "status_label": "已接入安全 Planner", "runtime_name": "security-findings.read", "runtime_role": "安全 Planner",
        "input_context": [
            {"name": "api_ids", "source": "安全评估选择", "description": "只查询所选 API 的历史问题。"},
            {"name": "limit", "source": "平台固定值", "description": "最多读取 20 条脱敏摘要。"},
        ],
        "output": "所选 API 未关闭 Finding 的脱敏摘要。",
        "constraints": ["不读取证据正文、响应正文或敏感请求数据。", "查询结果限制为本项目和所选 API。"],
        "audit": "通过安全只读工具写入 TaskToolInvocation。",
    },
    "security.inspect_web_session": {
        "status": "active", "status_label": "已接入安全 Planner", "runtime_name": "security-web.inspect", "runtime_role": "安全 Planner",
        "input_context": [
            {"name": "web_session_id", "source": "用户当前打开的受控会话", "description": "必须属于当前项目和安全评估环境。"},
        ],
        "output": "当前页面有限 DOM 信号和响应头观察结果。",
        "constraints": ["不导航、不点击、不提交表单。", "只检查用户已打开的受控页面。"],
        "audit": "通过安全只读工具写入 TaskToolInvocation。",
    },
    "security.confirm_plan": {
        "status": "active", "status_label": "受人工确认门控", "runtime_name": "security-plan.confirm", "runtime_role": "安全执行 Worker",
        "input_context": [
            {"name": "plan_version", "source": "当前任务方案", "description": "必须是用户明确确认的当前计划版本。"},
            {"name": "confirmed_by", "source": "当前登录用户", "description": "由服务端从授权会话识别，不接受模型伪造。"},
        ],
        "output": "确认后的安全用例范围和执行工作项。",
        "constraints": ["需要显式人工确认。", "模型不能代替用户确认风险。"],
        "audit": "记录确认人、计划版本、接受的用例索引和安全用例 ID。",
    },
    "security.execute_cases": {
        "status": "active", "status_label": "受人工确认门控", "runtime_name": "security-case.run", "runtime_role": "SECURITY_WORKER",
        "input_context": [
            {"name": "security_case_ids", "source": "人工确认后的安全计划", "description": "只执行确认后生成且仍有效的安全用例。"},
        ],
        "output": "已批准安全用例的执行状态、Finding 与证据关联信息。",
        "constraints": ["必须在用户确认后执行。", "限定登记 API、已确认策略和项目授权范围。"],
        "audit": "创建 TaskToolInvocation 并关联本次安全用例执行。",
    },
    "web_ui.generate_draft": {
        "status": "catalog_only", "status_label": "当前执行器未接入此工具键", "runtime_name": None, "runtime_role": "Web 用例草稿由独立 Web Authoring 流程处理",
        "input_context": [
            {"name": "web_session_id", "source": "受控浏览器会话", "description": "由独立 Web Authoring 流程管理。"},
        ],
        "output": "Web Authoring 流程可生成待确认草稿，但当前不是此工具键的调用实现。",
        "constraints": ["当前 Agent 白名单没有把此工具键映射到 web-case.draft。", "绑定此工具键不会触发草稿生成。"],
        "audit": "Web Authoring 操作使用其独立的会话、步骤和草稿审计记录。",
    },
}

_RUNTIME_CONTEXT_TYPES = {
    "project_id": "integer",
    "api_ids": "integer[]",
    "case_ids": "integer[]",
    "environment_id": "integer",
    "test_run_id": "integer",
    "approved_case_ids": "integer[]",
    "strategy_ids": "integer[]",
    "limit": "integer",
    "web_session_id": "integer",
    "plan_version": "integer",
    "confirmed_by": "user id",
    "security_case_ids": "integer[]",
}

for _tool in BUILTIN_TOOLS:
    _tool["runtime_details"] = TOOL_RUNTIME_DETAILS[_tool["key"]]
    for _field in _tool["runtime_details"]["input_context"]:
        _field.setdefault("type", _RUNTIME_CONTEXT_TYPES.get(_field["name"], "context"))
        _field.setdefault("required", True)

TOOL_BY_KEY = {item["key"]: item for item in BUILTIN_TOOLS}
