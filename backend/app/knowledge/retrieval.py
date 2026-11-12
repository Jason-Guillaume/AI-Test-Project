"""可测试的多路候选融合策略。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable


def reciprocal_rank_fusion(
    rankings: Iterable[Iterable[int | dict[str, Any]]], *, rank_constant: int = 60,
) -> list[dict[str, Any]]:
    """按 RRF 合并多个稳定 ID 排名；不把融合分数解释成相关性概率。"""
    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    scores: dict[int, float] = defaultdict(float)
    ranks: dict[int, dict[str, int]] = defaultdict(dict)
    first_seen: dict[int, int] = {}
    ordinal = 0
    for channel_index, ranking in enumerate(rankings):
        channel = f"channel_{channel_index + 1}"
        seen: set[int] = set()
        for rank, item in enumerate(ranking, start=1):
            ident = item.get("chunk_id") if isinstance(item, dict) else item
            if not isinstance(ident, int) or ident in seen:
                continue
            seen.add(ident)
            first_seen.setdefault(ident, ordinal)
            ordinal += 1
            scores[ident] += 1.0 / (rank_constant + rank)
            ranks[ident][channel] = rank
    return [
        {"chunk_id": ident, "score": scores[ident], "ranks": ranks[ident]}
        for ident in sorted(scores, key=lambda value: (-scores[value], first_seen[value], value))
    ]


def recall_at_k(ranked_ids: Iterable[int], relevant_ids: set[int], k: int) -> float | None:
    """检索工程 fixture 用 Recall@K；无相关来源标签时返回 None。"""
    if not relevant_ids:
        return None
    return len(set(list(ranked_ids)[:max(0, k)]) & relevant_ids) / len(relevant_ids)


def mean_reciprocal_rank(rankings: Iterable[Iterable[int]], relevant_by_query: Iterable[set[int]]) -> float | None:
    """检索工程 fixture 的 MRR；不用于衡量 Agent 答案质量。"""
    reciprocal_ranks = []
    for ranking, relevant in zip(rankings, relevant_by_query):
        if not relevant:
            continue
        reciprocal_ranks.append(next(
            (1 / rank for rank, ident in enumerate(ranking, start=1) if ident in relevant),
            0.0,
        ))
    return sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else None
