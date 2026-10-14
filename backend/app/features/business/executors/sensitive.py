"""敏感数据脱敏器。

执行日志中禁止保存 Authorization Token / Cookie / Password / Secret / API Key 的明文。
统一使用 SensitiveDataMasker 对所有 request_snapshot / response_snapshot 脱敏。

识别的敏感字段（不区分大小写）：
authorization, token, access_token, refresh_token, id_token, auth_token, cookie,
password, passwd, secret, secret_key, api_key, apikey, access_key, private_key,
signature, client_secret, sessionid, session_id, jsessionid
"""

from __future__ import annotations

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
    import re
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
