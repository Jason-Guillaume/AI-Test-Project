"""草稿系统规则质量检查。

只产出提示，不阻断审核，也不删除任何草稿。
LLM 审阅结论（批次 review_summary / review_gaps）只是建议，人工判断才是审核依据。
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from sqlalchemy.orm import Session

from app.features.test_management.models.test_case import TestCase

# 规则级别：error 强烈建议处理，warning 建议确认，info 仅供参考。
ERROR = "error"
WARNING = "warning"
INFO = "info"

# 「没有明确验证方式」的模糊措辞：预期只有这类词而没有可观察内容时提示。
_VAGUE_WORDS = ("正常", "正确", "合理", "成功", "符合预期", "符合要求", "ok", "success")
# 边界场景关键词：整个模块没有任何用例覆盖时在每条草稿上给 info。
BOUNDARY_WORDS = ("边界", "上限", "下限", "最大值", "最小值", "超长", "为空", "null", "boundary")
# 相似标题判定阈值。
_SIMILAR_RATIO = 0.85
# 参与相似度比对的正式用例名称上限，避免大项目全表扫描。
_EXISTING_NAME_LIMIT = 1000


def _normalize(title: str) -> str:
    """标题归一化：小写、去空白与标点，用于重复与相似比对。"""
    return re.sub(r"[\W_]+", "", title.lower())


def _is_vague(expected: list[str]) -> bool:
    """全部预期结果都只是模糊措辞时视为缺少明确验证方式。"""
    texts = [item.strip() for item in expected if item and item.strip()]
    if not texts:
        return False
    return all(any(word in item.lower() for word in _VAGUE_WORDS) and len(item) <= 12 for item in texts)


def check_draft(
    db: Session,
    *,
    project_id: int,
    payload: dict,
    sibling_titles: list[str],
    module_has_boundary: bool,
) -> list[dict]:
    """对一条草稿执行规则校验，返回问题列表（可为空）。

    sibling_titles：同批次其他草稿标题；module_has_boundary：同模块是否有用例覆盖边界场景。
    """
    issues: list[dict] = []
    title = str(payload.get("title") or "").strip()
    steps = [item for item in (payload.get("steps") or []) if str(item).strip()]
    expected = [item for item in (payload.get("expected_results") or []) if str(item).strip()]
    preconditions = [item for item in (payload.get("preconditions") or []) if str(item).strip()]
    coverage = " ".join(str(item) for item in (payload.get("coverage") or []))

    if not title:
        issues.append({"rule": "TITLE_EMPTY", "level": ERROR, "message": "用例标题为空"})
    else:
        normalized = _normalize(title)
        if normalized and any(_normalize(other) == normalized for other in sibling_titles):
            issues.append({"rule": "TITLE_DUPLICATE_IN_BATCH", "level": ERROR, "message": "本批次内存在相同标题的草稿"})
        existing = (
            db.query(TestCase.id, TestCase.name)
            .filter(TestCase.project_id == project_id)
            .order_by(TestCase.id.desc())
            .limit(_EXISTING_NAME_LIMIT)
            .all()
        )
        similar = [
            {"test_case_id": row.id, "name": row.name}
            for row in existing
            if normalized
            and (
                _normalize(row.name) == normalized
                or SequenceMatcher(None, _normalize(row.name), normalized).ratio() >= _SIMILAR_RATIO
            )
        ][:5]
        if similar:
            issues.append({
                "rule": "TITLE_SIMILAR_TO_EXISTING",
                "level": WARNING,
                "message": "与正式用例重名或高度相似，请确认不是重复用例",
                "similar_cases": similar,
            })
    if not steps:
        issues.append({"rule": "STEPS_EMPTY", "level": ERROR, "message": "测试步骤为空"})
    if not expected:
        issues.append({"rule": "EXPECTED_EMPTY", "level": ERROR, "message": "预期结果为空"})
    if steps and expected and len(steps) != len(expected):
        issues.append({
            "rule": "STEP_EXPECTED_MISMATCH",
            "level": WARNING,
            "message": f"测试步骤（{len(steps)} 条）与预期结果（{len(expected)} 条）数量不一致，请确认对应关系",
        })
    if not preconditions:
        issues.append({"rule": "PRECONDITION_MISSING", "level": WARNING, "message": "缺少前置条件"})
    if expected and _is_vague(expected):
        issues.append({"rule": "EXPECTED_VAGUE", "level": WARNING, "message": "预期结果缺少明确可验证的描述"})
    if not module_has_boundary and not any(word in coverage.lower() for word in BOUNDARY_WORDS):
        issues.append({"rule": "BOUNDARY_MISSING", "level": INFO, "message": "本模块草稿均未覆盖边界场景，可考虑补充"})
    return issues
