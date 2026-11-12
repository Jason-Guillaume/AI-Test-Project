"""模型配置模块：大模型连接配置管理。

保存 OpenAI 兼容接口的 api_base、model_name 与采样参数，API Key 加密落库。
响应白名单永远只回 has_api_key 与脱敏前缀，明文与密文都不外传。
"""
