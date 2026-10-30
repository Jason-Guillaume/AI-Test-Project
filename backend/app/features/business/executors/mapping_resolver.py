"""INPUT/OUTPUT 映射解析器。

INPUT Mapping：从 Runtime Context 提取业务变量 → 构造 HTTP 请求的各部分。
OUTPUT Mapping：从 HTTP 响应中提取值 → 写入 Runtime Context。
"""

from __future__ import annotations

import json

from app.core.expressions.paths import extract_dot_path, extract_jsonpath


def resolve_input_mappings(
    mappings: list[dict],
    context: dict[str, object],
    required_variables: dict[str, bool],
) -> tuple[dict, list[str]]:
    """解析 INPUT 映射，构造 HTTP 请求的各部分。

    Args:
        mappings: 映射列表，每项包含 direction, business_variable, api_location, api_field, expression。
        context: 运行时上下文变量。
        required_variables: 变量名 → 是否必填 的映射。

    Returns:
        (request_parts, errors) 元组。request_parts 包含 headers/query/path/body/cookies。
        errors 为错误信息列表（如缺失必填变量）。
    """
    headers: dict[str, str] = {}
    query: dict[str, str] = {}
    path_params: dict[str, str] = {}
    body_fields: dict[str, object] = {}
    cookies: dict[str, str] = {}
    errors: list[str] = []

    for m in mappings:
        if m.get("direction") != "INPUT":
            continue
        var_name = m.get("business_variable", "")
        location = m.get("api_location", "BODY").upper()
        api_field = m.get("api_field") or var_name

        # 从 context 获取变量值。
        value = context.get(var_name)
        if value is None:
            if required_variables.get(var_name, False):
                errors.append(f"Missing runtime variable: {var_name}")
            continue

        str_value = str(value)

        if location == "HEADER":
            headers[api_field] = str_value
        elif location == "QUERY":
            query[api_field] = str_value
        elif location == "PATH":
            path_params[api_field] = str_value
        elif location == "BODY":
            body_fields[api_field] = value
        elif location == "COOKIE":
            cookies[api_field] = str_value

    return {
        "headers": headers,
        "query": query,
        "path_params": path_params,
        "body": body_fields,
        "cookies": cookies,
    }, errors


def resolve_output_mappings(
    mappings: list[dict],
    response_body: str,
    required_variables: dict[str, bool],
) -> tuple[dict[str, object], list[str]]:
    """解析 OUTPUT 映射，从响应中提取变量值。

    Args:
        mappings: 映射列表。
        response_body: 响应体文本。
        required_variables: 变量名 → 是否必填 的映射。

    Returns:
        (extracted_vars, warnings) 元组。extracted_vars 为变量名→值。
        warnings 为警告信息列表。
    """
    extracted: dict[str, object] = {}
    warnings: list[str] = []

    # 尝试解析响应为 JSON。
    parsed_body: object = None
    try:
        parsed_body = json.loads(response_body) if response_body else None
    except (json.JSONDecodeError, TypeError):
        warnings.append("Response body is not valid JSON; OUTPUT extraction may fail")

    for m in mappings:
        if m.get("direction") != "OUTPUT":
            continue
        var_name = m.get("business_variable", "")
        expression = m.get("expression") or ""
        api_field = m.get("api_field") or ""

        value = _extract_from_response(parsed_body, expression, api_field)

        if value is None and required_variables.get(var_name, False):
            warnings.append(f"Required variable '{var_name}' could not be extracted from response")

        extracted[var_name] = value

    return extracted, warnings


def _extract_from_response(body: object, expression: str, api_field: str) -> object:
    """从响应体中提取值。

    优先级：
    1. 如果 expression 是 JSONPath（以 $ 开头），用 JSONPath 提取。
    2. 如果 api_field 存在，用点号路径提取。
    3. 否则返回 None。
    """
    if body is None:
        return None

    # JSONPath 提取。
    if expression and expression.startswith("$"):
        return extract_jsonpath(body, expression)

    # 点号路径提取（如 data.id → body["data"]["id"]）。
    if api_field:
        return extract_dot_path(body, api_field)

    return None
