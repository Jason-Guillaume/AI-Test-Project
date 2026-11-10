"""受控工作流模板目录。

本模块只声明 Agent 可选择的工作流元数据；图实现由 ``workflows.legacy`` 持有，
工具目录和治理配置通过单向兼容入口读取，工作流 key 与 HTTP 字段保持不变。
"""

WORKFLOW_TEMPLATES = {
    "api_test": {"label": "接口测试", "description": "接口理解、用例生成、执行与结果分析"},
    "web_ui": {"label": "Web UI 测试", "description": "页面观察、步骤规划与人工确认执行"},
    "security": {"label": "安全测试", "description": "安全测试计划、风险确认与结果分析"},
    "reporting": {"label": "测试报告", "description": "汇总执行结果并生成测试报告"},
    "asr_evaluation": {"label": "ASR 专项评测", "description": "显式调用 ASR 摘要与错误率工具；批次推理仍由 ASR 工作台执行"},
    "ai_evaluation": {"label": "AI 质量评审", "description": "显式规则校验与事实性、RAG、提示词注入专项评审；不接入自动测试 Worker"},
    "case_generation": {"label": "用例生成 · 主子协作", "description": "LangGraph 主 Agent 按模块调度用例生成子 Agent，汇总待人工审核的草稿"},
}
