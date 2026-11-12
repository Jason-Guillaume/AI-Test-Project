"""通用 HTTP 请求构建函数。

提供环境 URL、默认请求头及有序字段覆盖能力；接口目录如何加载参数与请求体由 api_catalog 负责。
"""

from __future__ import annotations

from typing import Any

from app.core.models.configuration import Environment


def build_environment_url(
    environment: Environment,
    path: str,
    path_params: dict[str, str] | None = None,
) -> str:
    """按环境 base_url、gateway_prefix、path 顺序拼接 URL 并替换路径参数。"""
    base = (environment.base_url or "").rstrip("/")
    gateway = (environment.gateway_prefix or "").rstrip("/")
    resolved_path = path or ""
    if path_params:
        for key, value in path_params.items():
            resolved_path = resolved_path.replace(f"{{{key}}}", str(value))
    return f"{base}{gateway}{resolved_path}"


def get_environment_headers(environment: Environment) -> dict[str, str]:
    """复制环境默认请求头并将键和值转换为字符串。"""
    if isinstance(environment.default_headers, dict):
        return {str(key): str(value) for key, value in environment.default_headers.items()}
    return {}


def merge_request_fields(*sources: dict[str, Any] | None) -> dict[str, Any]:
    """按参数顺序合并请求字段，后续来源覆盖前序同名值。"""
    merged: dict[str, Any] = {}
    for source in sources:
        if source:
            merged.update(source)
    return merged


__all__ = ["build_environment_url", "get_environment_headers", "merge_request_fields"]
