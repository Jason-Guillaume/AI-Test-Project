"""有资源上限的三方文本差异对齐。

算法以待测文本片段作为锚点，通过文本序列匹配参考片段；超过上限时完整保留原文并显式降级，
避免把未处理尾部报告为模型漏识别。该模块不计算准确率，也不判断哪家输出正确。
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Sequence

_MAX_ALIGN_CHARS = 20_000
_MAX_SEGMENT_CHARS = 120
_MAX_BLOCKS = 500
_MAX_RATIO_CHARS = 2_500
_BOUNDARY = re.compile(r"(?<=[。！？!?；;\n])")


def _split_text(value: str) -> list[str]:
    """按文本边界切分并限制单元长度，保留原始标点和字面内容。"""
    result: list[str] = []
    for chunk in _BOUNDARY.split(value):
        if not chunk:
            continue
        result.extend(chunk[index:index + _MAX_SEGMENT_CHARS] for index in range(0, len(chunk), _MAX_SEGMENT_CHARS))
    return result


def _map_to_anchor(anchor: Sequence[str], other: Sequence[str]) -> tuple[dict[int, str], dict[int, str]]:
    """按内容序列匹配一方片段到锚点，并单独记录锚点之间的插入文本。"""
    aligned: dict[int, list[str]] = {index: [] for index in range(len(anchor))}
    inserted: dict[int, list[str]] = {}
    matcher = difflib.SequenceMatcher(a=anchor, b=other, autojunk=True)
    for operation, a_start, a_end, b_start, b_end in matcher.get_opcodes():
        if operation == "equal":
            for offset in range(a_end - a_start):
                aligned[a_start + offset].append(other[b_start + offset])
        elif operation == "replace":
            # 用有界分桶把两侧替换片段完整配对，避免长度不等时丢弃尾部文本。
            anchor_width = a_end - a_start
            other_width = b_end - b_start
            if anchor_width == 0:
                inserted.setdefault(a_start, []).extend(other[b_start:b_end])
                continue
            for offset in range(anchor_width):
                low = b_start + (offset * other_width) // anchor_width
                high = b_start + ((offset + 1) * other_width) // anchor_width
                aligned[a_start + offset].extend(other[low:high])
        elif operation == "insert":
            inserted.setdefault(a_start, []).extend(other[b_start:b_end])
    flattened = {index: "".join(parts) for index, parts in aligned.items()}
    inserted_flat = {index: "".join(parts) for index, parts in inserted.items()}
    return flattened, inserted_flat


def align_triplet(test_text: str, reference_a_text: str, reference_b_text: str) -> tuple[list[dict[str, str]], bool]:
    """生成保留三方原文的差异块；返回 (块列表, 是否因资源上限降级)。"""
    values = (test_text or "", reference_a_text or "", reference_b_text or "")
    if max(map(len, values), default=0) > _MAX_ALIGN_CHARS:
        return [{"test_text": values[0], "reference_a_text": values[1], "reference_b_text": values[2]}], True
    anchor = _split_text(values[0])
    mapped_a, inserted_a = _map_to_anchor(anchor, _split_text(values[1]))
    mapped_b, inserted_b = _map_to_anchor(anchor, _split_text(values[2]))
    rows: list[dict[str, str]] = []
    for index in range(len(anchor) + 1):
        base = anchor[index] if index < len(anchor) else ""
        a_value = inserted_a.get(index, "")
        b_value = inserted_b.get(index, "")
        if index < len(anchor):
            a_value += mapped_a.get(index, "")
            b_value += mapped_b.get(index, "")
        # 一致片段也保留，供人工抽样；一致本身不表示任何模型正确。
        if base or a_value or b_value:
            rows.append({"test_text": base, "reference_a_text": a_value, "reference_b_text": b_value})
    if len(rows) > _MAX_BLOCKS:
        # 合并超限尾部到最后一个明确降级块，确保每方全文仍可从对比块中逐字重建。
        retained = rows[:_MAX_BLOCKS - 1]
        tail = rows[_MAX_BLOCKS - 1:]
        retained.append({
            key: "".join(row[key] for row in tail)
            for key in ("test_text", "reference_a_text", "reference_b_text")
        })
        return retained, True
    return rows, False


def edit_ratio(left: str, right: str) -> float | None:
    """计算有界字符编辑距离比例；超限时返回 None，不把它标成准确率或 CER。"""
    left = re.sub(r"\s+", "", left or "")
    right = re.sub(r"\s+", "", right or "")
    denominator = max(len(left), len(right))
    if denominator == 0:
        return 0.0
    if max(len(left), len(right)) > _MAX_RATIO_CHARS:
        return None
    # 只保留上一行和当前行，时间复杂度受输入上限约束，内存为 O(min(n,m))。
    if len(left) < len(right):
        left, right = right, left
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        for column, right_char in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + (left_char != right_char),
            ))
        previous = current
    return previous[-1] / denominator


__all__ = ["align_triplet", "edit_ratio"]
