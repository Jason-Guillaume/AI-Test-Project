"""受控工作流模板目录。

本模块只声明 Agent 可选择的工作流元数据；图实现由 ``workflows.legacy`` 持有，
工具目录和治理配置通过单向兼容入口读取，工作流 key 与 HTTP 字段保持不变。
"""

WORKFLOW_TEMPLATES = {
    "api_test": {"label": "接口测试", "description": "接口理解、用例生成、执行与结果分析"},
    "web_ui": {"label": "Web UI 测试", "description": "页面观察、步骤规划与人工确认执行"},
    "security": {"label": "安全测试", "description": "安全测试计划、风险确认与结果分析"},
    "reporting": {"label": "测试报告", "description": "汇总执行结果并生成测试报告"},
}
