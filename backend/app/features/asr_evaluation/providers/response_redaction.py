"""为 ASR 响应产物移除凭据和签名地址；不限制业务文本及数组长度。

仅处理已解析 JSON；结果为脱敏副本，不能宣称与远端原始字节相同。
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

REDACTION_VERSION = "asr-response-redaction-1"
_SECRET_FIELD = re.compile(r"(?:authorization|password|passwd|secret|token|api[-_]?key|cookie|credential|signature)", re.I)
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)
_BEARER = re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]+", re.I)
_ASSIGNMENT = re.compile(r"\b(?:token|secret|password|api[-_]?key|cookie|signature|credential)\s*[:=]\s*[^\s,;]+", re.I)
_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})\b")


def execution_secrets(execution: dict[str, Any]) -> list[str]:
    """提取已知凭据值，仅供内存中脱敏，不返回或记录密钥。"""
    result: list[str] = []

    def collect(value: Any) -> None:
        """递归处理嵌套请求参数，只收集敏感字段的字符串值。"""
        if isinstance(value, dict):
            for name, child in value.items():
                if str(name).lower() in {"secret_header", "credential_header"}:
                    continue
                if _SECRET_FIELD.search(str(name)) and isinstance(child, str) and child:
                    result.append(child)
                else:
                    collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(execution)
    return result


def redact_response(value: Any, secret: str | list[str] | None = None) -> tuple[Any, bool]:
    """递归复制响应并脱敏凭据字段、已知密钥及带查询串的 URL，返回是否改变。"""
    changed = False
    secrets = [secret] if isinstance(secret, str) else secret or []

    def visit(item: Any) -> Any:
        """保留 JSON 原有结构和完整业务文本，敏感字段及地址例外。"""
        nonlocal changed
        if isinstance(item, dict):
            result = {}
            for key, child in item.items():
                if _SECRET_FIELD.search(str(key)):
                    result[key] = "[已脱敏]"
                    changed = changed or child != "[已脱敏]"
                else:
                    result[key] = visit(child)
            return result
        if isinstance(item, list):
            return [visit(child) for child in item]
        if not isinstance(item, str):
            return item
        for known in sorted((value for value in secrets if value), key=len, reverse=True):
            if item == known or (len(known) >= 4 and known in item):
                item = item.replace(known, "[已脱敏]")
                changed = True
        for pattern in (_BEARER, _ASSIGNMENT, _KEY):
            item, count = pattern.subn("[已脱敏]", item)
            changed = changed or bool(count)

        def clean_url(match: re.Match[str]) -> str:
            """移除 URL 查询串、片段和用户信息，避免把签名地址写入产物。"""
            nonlocal changed
            original = match.group(0)
            try:
                parts = urlsplit(original)
            except ValueError:
                # 格式异常的地址无法可靠拆分，整体隐藏而不泄漏可能存在的凭据。
                changed = True
                return "[地址已脱敏]"
            if not (parts.query or parts.fragment or parts.username or parts.password):
                return original
            changed = True
            host = parts.netloc.rsplit("@", 1)[-1]
            return urlunsplit((parts.scheme, host, parts.path, "", "")) + "[地址参数已脱敏]"

        return _URL.sub(clean_url, item)

    return visit(value), changed
