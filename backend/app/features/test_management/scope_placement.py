"""测试范围归属的纯规则。

迁移和运行时共用方向映射、接口唯一匹配，避免同一条历史用例被挂到不同节点。
本模块不访问数据库。目录归属和被测对象是两件事：匹配失败必须留在待整理，不能按名称模糊挂靠。

已知限制：只识别 facets 能解析出的「方法 + 路径」；归一化后命中多条接口时放弃回填。
"""

from __future__ import annotations

from app.features.test_management.facets import normalize_path, parse_endpoint

DIRECTIONS = ("API", "UI", "AI")
NODE_TYPES = ("FOLDER", "ASSET_LINK", "INBOX")
ASSET_TYPES = (
    "API_MODULE",
    "API_INTERFACE",
    "BUSINESS_DOMAIN",
    "BUSINESS_FLOW",
    "BUSINESS_ACTION",
    "WEB_PAGE",
    "AGENT",
)
SCOPE_STATUSES = ("ACTIVE", "ARCHIVED")
INBOX_NAME = "待整理"


def direction_of_target(target_type: str | None) -> str:
    """把用例被测对象映射到三个测试方向。

    业务流和业务动作没有独立方向，归到 API 侧导航；界面对应 UI，模型与 Agent 对应 AI。
    认不出的取值也进 API，避免迁移时丢掉用例。
    """
    value = (target_type or "API").upper()
    if value == "WEB":
        return "UI"
    if value == "AI":
        return "AI"
    return "API"


def unique_interface_id(matches: list[int]) -> int | None:
    """仅在归一化后只命中一个接口时返回其 ID。

    零条或多条都返回 None。多条说明路径模板冲突，模糊挂接会造成错误关联。
    """
    distinct = list(dict.fromkeys(matches))
    if len(distinct) == 1:
        return distinct[0]
    return None


def interface_index(rows: list[tuple[int, str, str]]) -> dict[tuple[str, str], list[int]]:
    """按（方法, 归一化路径）收集接口 ID。同一键可以有多条，交给唯一匹配决定取舍。"""
    index: dict[tuple[str, str], list[int]] = {}
    for interface_id, method, path in rows:
        key = ((method or "").upper(), normalize_path(path or ""))
        index.setdefault(key, []).append(interface_id)
    return index


def backfill_api_id(description: str | None, index: dict[tuple[str, str], list[int]]) -> int | None:
    """从用例描述解析接口。无法唯一匹配时返回 None，调用方把用例留在待整理。"""
    parsed = parse_endpoint(description)
    if parsed is None:
        return None
    method, path = parsed
    return unique_interface_id(index.get((method.upper(), normalize_path(path)), []))
