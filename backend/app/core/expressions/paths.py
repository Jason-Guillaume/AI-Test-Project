"""受限 JSONPath 与字典路径读取。

支持业务映射、测试断言和 Web 比较当前使用的纯读取子集；缺失路径返回 None，不执行表达式代码。
"""

from __future__ import annotations


def extract_jsonpath(body: object, path: str) -> object:
    """按当前 JSONPath 子集读取对象，支持 `$`、点路径和非负数组索引。"""
    if not path.startswith("$"):
        return None
    expression = path[1:]
    if not expression:
        return body
    current = body
    for part in parse_jsonpath_parts(expression):
        if isinstance(part, int):
            if isinstance(current, list) and 0 <= part < len(current):
                current = current[part]
            else:
                return None
        elif isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def parse_jsonpath_parts(expression: str) -> list[str | int]:
    """把当前支持的点号和数组索引表达式解析为路径片段。"""
    parts: list[str | int] = []
    current = ""
    for char in expression:
        if char == ".":
            if current:
                parts.append(current)
            current = ""
        elif char == "[":
            if current:
                parts.append(current)
                current = ""
        elif char == "]":
            try:
                parts.append(int(current))
            except (ValueError, TypeError):
                pass
            current = ""
        else:
            current += char
    if current:
        parts.append(current)
    return parts


def extract_dot_path(body: object, path: str) -> object:
    """仅沿字典键逐段读取点路径；遇到缺失键或非字典值返回 None。"""
    current = body
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


__all__ = ["extract_dot_path", "extract_jsonpath", "parse_jsonpath_parts"]
