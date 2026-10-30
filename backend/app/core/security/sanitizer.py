"""Agent 上下文脱敏 + prompt injection 隔离（§22/§34/§35）。

职责：
- sanitize_context：递归脱敏上下文——先按「字段名」掩码（SensitiveDataMasker），
  再对每个字符串值按「值形态」掩码（webhook 地址 / 承载凭证的 URL 参数 / secret 令牌）。
  两层是叠加关系，不能互相替代：SensitiveDataMasker 只看键名，而 webhook 与签名密钥
  经常出现在 error_message、断言消息这类自由文本字段里，键名不在敏感集合中。
- sanitize_text：自由文本的敏感值占位化（Authorization 头 / key=value / 值形态）。
- build_chat_messages：把系统指令固定在 system role、业务数据一律作为 user content，
  避免「业务数据文本被当作系统指令执行」（§35）。Tool 调用权限由代码控制，不由 LLM 文本决定。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.security.sensitive import SensitiveDataMasker, is_sensitive_key

_TEXT_MASKED = "******"

# 用于把 Authorization 占位化的正则：把 "Bearer <真实token>" 之类替换为占位。
_AUTHORIZATION_PATTERN = re.compile(
    r"(authorization\s*[:=]\s*)(bearer\s+\S+|basic\s+\S+|\S+)",
    re.IGNORECASE,
)
_AUTH_PLACEHOLDER = r"\1Bearer ${token}"

# 自由文本中 key=value / key:value 模式的敏感值掩码（补充 SensitiveDataMasker.mask_text
# 仅覆盖 = 分隔符且关键词不全的缺陷）。
_SENSITIVE_TEXT_PATTERN = re.compile(
    r"(authorization|token|access_token|refresh_token|id_token|auth_token|"
    r"cookie|set_cookie|password|passwd|secret|secret_key|api_key|apikey|"
    r"access_key|private_key|signature|client_secret|sessionid|session_id|jsessionid)"
    r"[\"']?\s*([=:：])\s*(\"[^\"]*\"|'[^']*'|[^\",;\s]+)",
    re.IGNORECASE,
)

# ---- 值形态脱敏（§22：Webhook URL / Secret 不进 Agent Prompt、报告与接口响应）----
# 本测试平台自己的用例就会断言「响应体不含 webhook」，所以 webhook 出现在断言消息、
# error_message 里是正常测试数据，必须能识别出来；只按字段名脱敏是拦不住的。
# URL / 凭证值的结束边界：空白、引号、尖括号，以及中英文括号与句读标点。
# 全角左括号「（」必须也列入——否则「.../hook/<id>（secret xxx）」里的 URL 会一路吞到
# 下一个空格，把括号和紧随其后的 secret 关键词一起吃掉，反而把密钥值裸留在文本里。
# 长度上限避免在极长无空格文本上失控回溯。
_URL_STOP = r"\s\"'<>，。；、：（）()【】\[\]{}「」『』《》〈〉"
_URL_TAIL = r"[^%s]{1,512}" % _URL_STOP
_URL_BOUND = r"(?=[^%s]|$)" % _URL_STOP

# 机器人回调地址：飞书 /open-apis/bot/v2/hook/<id>、/hook/<id>、钉钉 /robot/send、
# 企业微信 /cgi-bin/webhook/send。整条 URL 掩掉。
# 允许 userinfo（https://user:pass@host/...）：urlparse 也保留在 netloc 里，
# 不带上这个可选分组，地址里的账号密码就会原样漏出去。
_WEBHOOK_URL_PATTERN = re.compile(
    r"https?://(?:[\w.\-@:]+@)?"
    r"[_\.\-0-9A-Za-z]+[_\.\-0-9A-Za-z:/*]*"
    r"(?:/open-apis/bot/v2/hook/|/hook/|/robot/send|/webhook/send)" + _URL_TAIL,
    re.IGNORECASE,
)
_WEBHOOK_PLACEHOLDER = "https://<webhook已脱敏>"

# 任意 URL 查询串中的凭证参数（钉钉 ?access_token=、企微 ?key=、通用 sign/secret）。
_SECRET_QUERY_PATTERN = re.compile(
    r"(?i)([?&](?:access_token|auth_token|token|key|sign|signature|secret|"
    r"app_secret|bot_secret|webhook|password|passwd)\s*=)" + _URL_TAIL + _URL_BOUND
)

# 「secret / sign / webhook / token」后跟一个足够长的凭据串（覆盖 `secret test-xxx-42`、
# `sign <签名>` 这类空格分隔写法；飞书请求体里的 sign 就是 HMAC 签名，属凭证）。
# 要求 ≥16 位且为连续标识符字符，避免误伤普通英文单词（`sign off` 之类不会命中）。
_SECRET_TOKEN_PATTERN = re.compile(
    r"(?i)\b(secret|sign|signing[_\-\s]?key|webhook|token|password|api[_\-\s]?key)\b"
    r"[\"']?\s*[:：=]?\s*[\"']?([A-Za-z0-9_\-]{16,})"
)


def mask_secret_values(text: str) -> str:
    """按「值形态」掩码自由文本里的 webhook 地址与凭证。

    与字段名脱敏叠加调用，**不能**替代它：字段名掩码处理结构化键，这里处理
    以字符串值形式出现的凭证（断言消息、error_message、LLM 回显）。
    """
    text = _WEBHOOK_URL_PATTERN.sub(_WEBHOOK_PLACEHOLDER, text)
    text = _SECRET_QUERY_PATTERN.sub(r"\1" + _TEXT_MASKED, text)
    text = _SECRET_TOKEN_PATTERN.sub(r"\1" + _TEXT_MASKED, text)
    return text


def _walk_mask_values(value: Any) -> Any:
    """递归对字符串值做值形态掩码；非字符串原样返回。"""
    if isinstance(value, dict):
        return {k: _walk_mask_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk_mask_values(v) for v in value]
    if isinstance(value, str):
        return mask_secret_values(value)
    return value


def sanitize_context(context: Any) -> Any:
    """递归脱敏上下文（用于入 prompt / 落库 / 回响应前清洗）。

    两层叠加：字段名敏感值整体掩码 → 所有字符串值再做值形态掩码。
    """
    if context is None:
        return None
    return _walk_mask_values(SensitiveDataMasker.mask_body(context))


def sanitize_text(text: str | None) -> str | None:
    """对自由文本做敏感值占位化（§22/§34）。

    覆盖三层：
    1. Authorization 头（Bearer/Basic 格式）→ 占位符
    2. key=value / key:value 模式的敏感值（password/token/cookie/secret/...）→ 掩码
    3. 值形态：webhook 回调地址、URL 里的凭证参数、secret 令牌串 → 掩码
    """
    if not text:
        return text
    # 先把 "Authorization: Bearer xxxx" 折叠为占位。
    text = _AUTHORIZATION_PATTERN.sub(_AUTH_PLACEHOLDER, text)
    # 再处理 key=value / key:value 格式的敏感值。
    text = _SENSITIVE_TEXT_PATTERN.sub(r"\1\2" + _TEXT_MASKED, text)
    # 最后按值形态掩码（webhook 地址 / 签名密钥），补齐字段名脱敏覆盖不到的自由文本。
    text = mask_secret_values(text)
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


def mask_known_secrets(value: Any, secrets: list[str] | tuple[str, ...]) -> Any:
    """按字段名和本轮已知凭据值递归脱敏，不依赖任何执行器或领域模型。"""
    if isinstance(value, dict):
        value = dict(value)
        # HTTP 头对象可能使用 Playwright 的 name/value 数组表示。
        if isinstance(value.get("name"), str) and is_sensitive_key(value["name"]) and "value" in value:
            value["value"] = "***"
        for key in ("headers", "cookies", "storageState"):
            if key in value:
                value[key] = "***"
        return {key: mask_known_secrets(item, secrets) for key, item in sanitize_context(value).items()}
    if isinstance(value, list):
        return [mask_known_secrets(item, secrets) for item in value]
    if isinstance(value, str):
        known = {str(secret) for secret in secrets if secret}
        if value in known:
            return "***"
        for secret in sorted((item for item in known if len(item) >= 4), key=len, reverse=True):
            value = value.replace(secret, "***")
    return value


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
