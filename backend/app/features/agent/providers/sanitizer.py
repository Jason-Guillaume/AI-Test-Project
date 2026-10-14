"""Agent 上下文脱敏 + prompt injection 隔离（§34/§35）。

职责：
- sanitize_context/sanitize_messages：复用 business.executors.sensitive 的
  SensitiveDataMasker，发送给 LLM 前过滤 password/token/cookie/api_key/secret/
  refresh_token/authorization 等真实值（保留 `Authorization: Bearer ${token}` 占位）。
- build_chat_messages：把系统指令固定在 system role、业务数据一律作为 user content，
  避免「业务数据文本被当作系统指令执行」（§35）。Tool 调用权限由代码控制，不由 LLM 文本决定。
"""

from __future__ import annotations

from typing import Any

from app.features.business.executors.sensitive import SensitiveDataMasker

# 用于把 Authorization 占位化的正则：把 "Bearer <真实token>" 之类替换为占位。
import re

_AUTHORIZATION_PATTERN = re.compile(
    r"(authorization\s*[:=]\s*)(bearer\s+\S+|basic\s+\S+|\S+)",
    re.IGNORECASE,
)
_AUTH_PLACEHOLDER = r"\1Bearer ${token}"


def sanitize_context(context: Any) -> Any:
    """递归脱敏上下文中的敏感字段值（用于入 prompt 前清洗）。"""
    if context is None:
        return None
    return SensitiveDataMasker.mask_body(context)


# 自由文本中 key=value / key:value 模式的敏感值掩码（补充 SensitiveDataMasker.mask_text
# 仅覆盖 = 分隔符且关键词不全的缺陷）。
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(authorization|token|access_token|refresh_token|id_token|auth_token|"
    r"cookie|set_cookie|password|passwd|secret|secret_key|api_key|apikey|"
    r"access_key|private_key|signature|client_secret|sessionid|session_id|jsessionid)"
    r"([=:])\s*([^\s,;\"']+)",
    re.IGNORECASE,
)
_TEXT_MASKED = "******"


def sanitize_text(text: str | None) -> str | None:
    """对自由文本做敏感值占位化（§34）。

    覆盖两层：
    1. Authorization 头（Bearer/Basic 格式）→ 占位符
    2. key=value / key:value 模式的敏感值（password/token/cookie/secret/...）→ 掩码
    """
    if not text:
        return text
    # 先把 "Authorization: Bearer xxxx" 折叠为占位。
    text = _AUTHORIZATION_PATTERN.sub(_AUTH_PLACEHOLDER, text)
    # 再处理 key=value / key:value 格式的敏感值。
    text = _SENSITIVE_TEXT_PATTERN.sub(r"\1\2" + _TEXT_MASKED, text)
    return text


def build_chat_messages(
    system: str, user_content: str, *, history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """构造 OpenAI 兼容的 messages 数组，强制 system/user 角色隔离（§35）。

    - system 仅放平台固定指令（本文件调用方传入的常量 prompt），**不**拼业务数据。
    - 业务数据（接口/业务/测试资产）一律进 user content，被当作数据而非指令。
    - history 中的 ASSISTANT 消息保留为 assistant 角色，提供多轮上下文。
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    if history:
        # history 已脱敏；只取 role/content 两个字段，丢弃 metadata。
        for item in history[-8:]:  # 截断，控制 token
            role = item.get("role")
            content = item.get("content")
            if role in ("USER", "user") and content:
                messages.append({"role": "user", "content": content})
            elif role in ("ASSISTANT", "assistant") and content:
                messages.append({"role": "assistant", "content": content})
    messages.append({"role": "user", "content": user_content})
    return messages


def assert_no_real_secret(payload: str, *, forbidden: tuple[str, ...]) -> list[str]:
    """断言 payload 不含给定禁止串（测试用：验证真实 token 未进 LLM payload）。

    返回命中的禁止串列表（空表示通过）。
    """
    hits: list[str] = []
    low = payload.lower()
    for token in forbidden:
        if token and token.lower() in low:
            hits.append(token)
    return hits
