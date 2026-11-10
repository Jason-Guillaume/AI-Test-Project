"""测试资产双维拆解的纯函数。

用例库已从「范围树」改为 被测对象 × 用例维度 交叉矩阵（覆盖矩阵见 case_service.coverage）。
存量导入数据把两个维度压在一个路径里（测试点描述「路径：接口测试 / 边界测试 / 登录接口」），
本模块负责把路径拆回两个维度，并从用例描述里解析接口地址用于回填 api_id。

只处理字符串，不访问数据库；整理脚本与测试共用，避免两套规则。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NAME_LIMIT = 200
_ENDPOINT_RE = re.compile(r"(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s]+)")
_PATH_PARAM_RE = re.compile(r"\{[^}]+\}")
_PATH_DIGITS_RE = re.compile(r"(?<=/)\d+(?=/|$)")
# 测试点名字的路径前缀（导入时写成「范围·A / B / C」）。
_SCOPE_PREFIX = "范围·"

# 对象段（路径第一段）→ target_type。
_TARGET_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("API", ("接口", "API", "Mock", "后端")),
    ("WEB", ("前端", "前台", "后台", "界面", "UI")),
    ("BUSINESS_FLOW", ("业务", "流程")),
)
# AI 对象只在没有命中上面任何对象词时兜底：
# 「AI 混剪前台」归 WEB（是界面），「AI 调用接口专项」归 API（是接口），
# 「LangGraph 智能体专项」这类才归 AI。
_AI_WORDS = ("AI", "智能", "模型")

# 维度段（路径第二段）→ case_type。顺序即优先级，先命中的先用。
_DIMENSION_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SECURITY", ("安全", "越权")),
    ("PERMISSION", ("权限", "鉴权")),
    ("BOUNDARY", ("边界",)),
    ("NEGATIVE", ("负向", "负面")),
    ("EXCEPTION", ("异常",)),
    ("BUSINESS", ("业务",)),
    ("FUNCTIONAL", ("功能",)),
)


@dataclass(frozen=True)
class ScopeFacets:
    """一段范围路径拆出的三维信息。"""

    target_type: str | None  # 被测对象；认不出时为 None（AI 在其他对象词不命中时兜底）
    case_type: str | None    # 测试维度；路径里没有维度段时为 None
    leaf: str                # 叶子场景名（路径最后一段）


def clip(value: str, limit: int = _NAME_LIMIT) -> str:
    """截断到字段长度，避免写入时被拒。"""
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _match_words(text: str, table: tuple[tuple[str, tuple[str, ...]], ...]) -> str | None:
    """按词表把一段路径文字映射到枚举值，认不出返回 None。"""
    for value, words in table:
        if any(word in text for word in words):
            return value
    return None


def parse_scope_path(path: str) -> ScopeFacets | None:
    """把「接口测试 / 边界测试 / 登录接口」拆成 对象 + 维度 + 叶子场景。

    第一段定被测对象，第二段定测试维度（可缺），剩余最后一段是叶子场景名。
    认不出对象（空路径等）时返回 None，调用方保持原数据不动。
    AI 类对象在其他对象词都不命中时兜底归 AI。
    """
    # 导入时大纲用「 / 」连接（带空格）；场景名里可能自带裸「/」（如「加载/空态」），
    # 只按带空格的分隔符切，避免把场景名拦腰截断。
    segments = [segment.strip() for segment in re.split(r"\s+/\s*", path) if segment.strip()]
    if not segments:
        return None
    head = segments[0]
    target_type = _match_words(head, _TARGET_WORDS)
    if target_type is None and any(word in head for word in _AI_WORDS):
        target_type = "AI"
    if target_type is None:
        return None
    case_type = _match_words(segments[1], _DIMENSION_WORDS) if len(segments) >= 2 else None
    return ScopeFacets(target_type=target_type, case_type=case_type, leaf=segments[-1])


def scope_path_of_point(name: str, description: str | None) -> str:
    """取测试点的范围路径：优先描述里的「路径：」行，退化用名字去掉「范围·」前缀。

    名字可能带「·2」这类去重后缀，描述里的路径是导入时的原始大纲，更可靠。
    """
    for line in (description or "").split("\n"):
        text = line.strip()
        if text.startswith(("路径：", "路径:")):
            return text.split("：", 1)[-1].split(":", 1)[-1].strip()
    if name.startswith(_SCOPE_PREFIX):
        return name[len(_SCOPE_PREFIX):]
    return ""


def parse_endpoint(description: str | None) -> tuple[str, str] | None:
    """从用例描述的「模块路径」/「画布」行解析（方法, 路径），对不上返回 None。"""
    for line in (description or "").split("\n"):
        text = line.strip()
        if not text.startswith(("模块路径", "画布")):
            continue
        matched = _ENDPOINT_RE.search(text)
        if matched:
            return matched.group(1), matched.group(2)
    return None


def normalize_path(path: str) -> str:
    """归一化接口路径：去查询串与尾斜杠，{param} 模板与纯数字段都收成 {}，方便两侧对齐。"""
    text = path.split("?", 1)[0].rstrip("/") or "/"
    text = _PATH_PARAM_RE.sub("{}", text)
    return _PATH_DIGITS_RE.sub("{}", text)
