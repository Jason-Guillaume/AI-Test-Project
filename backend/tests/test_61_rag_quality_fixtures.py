"""小型检索工程 fixture：覆盖中文、英文和中英混合，不评分 Agent 答案。"""

from types import SimpleNamespace

from app.knowledge.retrieval import mean_reciprocal_rank, recall_at_k
from app.knowledge.service import _bm25_scores


def test_rag_lexical_fixtures_report_recall_at_k_and_mrr():
    chunks = [
        SimpleNamespace(id=1, text="退款必须通过原支付渠道退回"),
        SimpleNamespace(id=2, text="API timeout retries use exponential backoff"),
        SimpleNamespace(id=3, text="混合检索 combines BM25 with permission filtered context"),
        SimpleNamespace(id=4, text="无关的部署说明和天气预报"),
    ]
    cases = [
        ("退款 原支付渠道", {1}),
        ("API timeout retries", {2}),
        ("混合检索 BM25 context", {3}),
    ]
    rankings = []
    recalls = []
    for query, relevant in cases:
        scores = _bm25_scores(chunks, query)
        ranking = [row.id for row in sorted(chunks, key=lambda item: (-scores[item.id], item.id))]
        ranking = [ident for ident in ranking if scores[ident] > 0]
        rankings.append(ranking)
        recalls.append(recall_at_k(ranking, relevant, 1))

    assert recalls == [1.0, 1.0, 1.0]
    assert mean_reciprocal_rank(rankings, [relevant for _, relevant in cases]) == 1.0
    assert recall_at_k([1, 2], set(), 2) is None
