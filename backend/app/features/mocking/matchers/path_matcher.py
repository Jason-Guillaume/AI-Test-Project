"""路径匹配：把请求 path 与 Endpoint 的 path 模式（支持 ``{param}``）匹配。

第一阶段只支持固定段与单段 ``{param}``，不支持复杂正则（§十）。
匹配成功时把 ``{param}`` 对应的请求段注入 path_params，供 Response Template 用
（``${request.path.<param>}``）。
"""

from __future__ import annotations

_PARAM_OPEN = "{"
_PARAM_CLOSE = "}"


def _split_segments(path: str) -> list[str]:
    """按 ``/`` 切段，去掉首尾空段，不做 URL 解码（与 Endpoint path 同源存储）。"""
    return [seg for seg in (path or "").split("/") if seg != ""]


def match_path(pattern: str, actual_path: str) -> tuple[bool, dict[str, str]]:
    """匹配请求 path 与 Endpoint path 模式。

    Args:
        pattern: Endpoint 配置的 path，如 ``/payment/{payment_id}``。
        actual_path: 运行时请求路径（去掉 service 前缀后的部分），如 ``/payment/123``。

    Returns:
        (是否匹配, path_params)。匹配失败返回 ``(False, {})``。
    """
    pat_segments = _split_segments(pattern)
    req_segments = _split_segments(actual_path)
    if len(pat_segments) != len(req_segments):
        return False, {}

    params: dict[str, str] = {}
    for pat, req in zip(pat_segments, req_segments, strict=False):
        if pat.startswith(_PARAM_OPEN) and pat.endswith(_PARAM_CLOSE) and len(pat) > 2:
            param_name = pat[1:-1]
            if not param_name:
                return False, {}
            params[param_name] = req
        elif pat != req:
            return False, {}
    return True, params


__all__ = ["match_path"]
