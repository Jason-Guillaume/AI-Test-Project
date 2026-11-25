"""小型检索工程 fixture：覆盖中文、英文和中英混合，不评分 Agent 答案。"""

from types import SimpleNamespace

from app.knowledge.retrieval import mean_reciprocal_rank, recall_at_k
from app.knowledge.service import _bm25_scores
from scripts.evaluate_superagent_retrieval import evaluate_case


def test_evaluation_caps_vector_candidates_after_permission_filter():
    corpus = {key: SimpleNamespace(id=key, position=0, version_id=key, project_id=key, text="same")
              for key in (1, 2)}
    case = dict(id="scope", project_id=2, agent_id=7, visible_versions=[2], relevant_chunks=[2],
                answerable=True, query="same", vector={'status': 'ACTIVE', 'ids': [1, 2]})
    config = dict(top_k=1, bm25_candidates=1, vector_candidates=1, rerank_window=1)
    vector = evaluate_case(case, corpus, config)['variants']['VECTOR']
    assert vector['hits'] == [2] and vector['unauthorized_candidates_filtered'] == 1


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
