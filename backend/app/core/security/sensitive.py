"""敏感数据脱敏器。

执行日志中禁止保存 Authorization Token / Cookie / Password / Secret / API Key 的明文。
统一使用 SensitiveDataMasker 对所有 request_snapshot / response_snapshot 脱敏。

识别的敏感字段（不区分大小写）：
authorization, token, access_token, refresh_token, id_token, auth_token, cookie,
password, passwd, secret, secret_key, api_key, apikey, access_key, private_key,
signature, client_secret, sessionid, session_id, jsessionid
"""

from __future__ import annotations

import json
import re

# 敏感字段名集合（小写，精确匹配）。刻意不做「含 session / 含 token 就命中」的
# 子串匹配：session_count、token_type 这类非秘密字段会被一起掩掉。需要新凭证名时
# 显式加到集合里，行为可预期、可 review。
_SENSITIVE_KEYS = frozenset({
    "authorization",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "auth_token",
    "mock_token",
    "cookie",
    "set_cookie",
    "password",
    "passwd",
    "secret",
    "secret_key",
    "api_key",
    "apikey",
    "access_key",
    "accesskey",
    "private_key",
    "signature",
    "client_secret",
    "sessionid",
    "session_id",
    "jsessionid",
})

# 脱敏后的占位值。
_MASKED = "******"


def is_sensitive_key(key: str) -> bool:
    """判断字段名是否为敏感字段。

    归一化：大小写不敏感，并把 '-'/' ' 视作 '_'——HTTP 头习惯用连字符
    （x-api-key、set-cookie），JSON 字段习惯用下划线（access_key），
    两者指同一类凭证，必须先归一否则变体名会漏脱敏。
    """
    normalized = (key or "").lower().replace("-", "_").replace(" ", "_")
    if normalized in _SENSITIVE_KEYS:
        return True
    # HTTP 头的 x- 前缀变体：x-api-key / x-auth-token / x-access-key / x-secret。
    # 去掉前缀后再比对一次，否则这类自定义认证头会全部漏脱敏。
    if normalized.startswith("x_"):
        return normalized[2:] in _SENSITIVE_KEYS
    return False


def mask_headers(headers: dict[str, str] | None) -> dict[str, str]:
    """脱敏请求头/响应头中的敏感值。"""
    if not headers:
        return {}
    result: dict[str, str] = {}
    for key, value in headers.items():
        if is_sensitive_key(key):
            result[key] = _MASKED
        else:
            result[key] = str(value)
    return result


# 已经脱敏的占位值：再次脱敏时保持原样，避免把「******」换成另一种占位。
_MASKED_VALUE_PATTERN = re.compile(
    r"(?i)^(?:(?:bearer|basic|token)\s+)?(?:\*{3,}|\$\{token\}|<[^>]+>)$"
)
# 原始请求头的 name: value / name=value 行；请求行（GET /path）没有分隔符会被跳过。
_HEADER_LINE_PATTERN = re.compile(r"^(\s*)([^:=\r\n]+?)(\s*[:=]\s*)(.*)$")


def _is_masked_value(value: str) -> bool:
    """判断请求头值是否已经是占位符，避免重复改写用户已脱敏的样本。"""
    return bool(_MASKED_VALUE_PATTERN.match((value or "").strip()))


def _mask_header_node(node: object, state: list[bool]) -> object:
    """递归脱敏 JSON 形式的请求头，支持字典与 Playwright 的 name/value 数组。"""
    if isinstance(node, dict):
        name = node.get("name")
        if isinstance(name, str) and is_sensitive_key(name) and "value" in node:
            value = node["value"]
            if isinstance(value, str) and not _is_masked_value(value):
                node["value"] = _MASKED
                state[0] = True
        for key, value in list(node.items()):
            if isinstance(value, str):
                if is_sensitive_key(str(key)) and not _is_masked_value(value):
                    node[key] = _MASKED
                    state[0] = True
            elif isinstance(value, (dict, list)):
                _mask_header_node(value, state)
        return node
    if isinstance(node, list):
        for item in node:
            _mask_header_node(item, state)
        return node
    return node


def mask_header_text(text: str | None) -> str | None:
    """脱敏 JSON 或逐行原始文本形式的请求头，保留普通头供排查。

    识别不区分大小写，并覆盖 ``X-API-Key`` / ``X-Auth-Token`` 等 ``x-`` 变体；
    Authorization、Cookie 等敏感值整体替换为占位符，Content-Type 等普通头原样保留。
    已经是占位符的输入不会被再次改写。
    """
    if not text:
        return text
    stripped = text.strip()
    if not stripped:
        return text
    state = [False]
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        masked = _mask_header_node(parsed, state)
        return json.dumps(masked, ensure_ascii=False) if state[0] else text
    lines = text.splitlines()
    output: list[str] = []
    for line in lines:
        match = _HEADER_LINE_PATTERN.match(line)
        if match is None:
            output.append(line)
            continue
        indent, name, separator, value = match.groups()
        if is_sensitive_key(name) and not _is_masked_value(value):
            output.append(f"{indent}{name}{separator}{_MASKED}")
            state[0] = True
        else:
            output.append(line)
    return "\n".join(output) if state[0] else text


def mask_body(body: object) -> object:
    """脱敏请求体/响应体中的敏感值。

    递归遍历 dict/list，将敏感键的值替换为占位符。
    """
    if isinstance(body, dict):
        result: dict[str, object] = {}
        for key, value in body.items():
            if is_sensitive_key(str(key)):
                result[key] = _MASKED
            else:
                result[key] = mask_body(value)
        return result
    if isinstance(body, list):
        return [mask_body(item) for item in body]
    return body


def mask_text(text: str | None) -> str | None:
    """对纯文本做简单脱敏：如果包含 token= 或 password= 模式，替换为占位符。

    主要用于 Content-Type 为 text/plain 或 form-urlencoded 的 body。
    """
    if not text:
        return text
    result = text
    # 替换 key=value 模式中的敏感值。
    result = re.sub(
        r"(authorization|token|access_token|refresh_token|password|secret|api_key|apikey)"
        r"=([^\s&]+)",
        r"\1=" + _MASKED,
        result,
        flags=re.IGNORECASE,
    )
    return result


class SensitiveDataMasker:
    """敏感数据脱敏器。无状态，可全局复用。"""

    @staticmethod
    def mask_request(method: str, url: str, headers: dict[str, str] | None,
                     query: dict[str, str] | None, body: object, body_type: str = "json") -> dict:
        """构造脱敏后的请求快照。"""
        masked_headers = mask_headers(headers)
        if body_type == "json" and isinstance(body, (dict, list)):
            masked_body = mask_body(body)
        elif body_type == "raw" and isinstance(body, str):
            masked_body = mask_text(body)
        else:
            masked_body = body if isinstance(body, (dict, list, str)) else str(body)

        # URL 中的查询参数也可能包含敏感信息。
        from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
        parsed = urlsplit(url)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        masked_pairs = [
            (k, _MASKED if is_sensitive_key(k) else v)
            for k, v in query_pairs
        ]
        if masked_query := query:
            for k, v in masked_query.items():
                if is_sensitive_key(k):
                    masked_pairs.append((k, _MASKED))

        masked_url = urlunsplit((
            parsed.scheme, parsed.netloc, parsed.path,
            urlencode(masked_pairs), parsed.fragment,
        ))

        return {
            "method": method.upper(),
            "url": masked_url,
            "headers": masked_headers,
            "query": {
                str(k): (_MASKED if is_sensitive_key(k) else str(v))
                for k, v in (query or {}).items()
            },
            "body": masked_body,
            "body_type": body_type,
        }

    @staticmethod
    def mask_response(status_code: int, headers: dict[str, str] | None,
                      body: object) -> dict:
        """构造脱敏后的响应快照。"""
        masked_headers = mask_headers(headers)
        if isinstance(body, (dict, list)):
            masked_body = mask_body(body)
        elif isinstance(body, str):
            masked_body = mask_text(body)
        else:
            masked_body = str(body) if body is not None else None

        return {
            "status_code": status_code,
            "headers": masked_headers,
            "body": masked_body,
        }

    @staticmethod
    def mask_body(body: object) -> object:
        """脱敏请求体/响应体中的敏感值。

        委托模块级 ``mask_body``（递归遍历 dict/list，将敏感键的值替换为占位符）。
        执行器在保存运行时上下文 / Action 输出快照时统一经此入口脱敏。
        """
        return mask_body(body)
