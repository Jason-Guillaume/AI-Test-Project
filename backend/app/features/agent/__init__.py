"""接口测试 Agent（feature-local）。

Agent 只做理解/规划/生成/分析/调用，不重新实现 HTTP 执行、业务流执行、断言、
TestRun——这些复用既有 business / test_management 能力。

编排用 langgraph StateGraph（节点+边+interrupt_before 暂停）；持久化用自建
agent_session/agent_message 表（§26），每次 HTTP 请求从 DB 重建 AgentState 后
全新 invoke，不依赖 langgraph checkpointer。LLMProvider 自写（httpx 调 OpenAI
兼容，从 ModelConfiguration 取默认配置）。
"""
