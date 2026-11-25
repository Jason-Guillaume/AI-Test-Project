"""在同一授权语料上重放词法、向量、融合和重排，输出逐题排名与汇总指标。"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge.retrieval import reciprocal_rank_fusion
from app.knowledge.service import _bm25_scores, _terms


def lexical_search(rows, query, limit):
    """使用运行时分词和 BM25，在授权片段内重放候选筛选与排序。"""
    terms = list(dict.fromkeys(_terms(query)))[:64]
    matches = [(sum(term in row.text.lower() for term in terms), row) for row in rows]
    candidates = [row for count, row in sorted(matches, key=lambda match: (
        -match[0], match[1].version_id, match[1].position, match[1].id,
    ))[:limit] if count]
    scores = _bm25_scores(candidates, query)
    return [row.id for row in sorted(candidates, key=lambda row: (-scores[row.id], row.version_id, row.position, row.id))
            if scores[row.id] > 0]


def replay_rerank(ranking, capture, window, minimum_score):
    """给已授权的候选重放模型分数。未采集或请求失败时保留输入排序。"""
    if not capture or capture.get('status') != 'ACTIVE' or not ranking:
        return ranking, False
    scores = {int(key): float(value) for key, value in capture['scores'].items()}
    candidates = ranking[:window]
    if set(candidates) - scores.keys():
        raise ValueError('重排采集缺少窗口内片段的分数')
    return [ident for ident in sorted(candidates, key=scores.__getitem__, reverse=True)
            if minimum_score is None or scores[ident] >= minimum_score], True


def evaluate_case(case, corpus, config):
    """将每个策略限制在同一项目、Agent 样本和可见版本，记录候选与命中。"""
    visible = set(case['visible_versions'])
    permitted = {ident for ident, row in corpus.items()
                 if row.project_id == case['project_id'] and row.version_id in visible}
    relevant = set(case['relevant_chunks'])
    if relevant - permitted or bool(relevant) != case['answerable']:
        raise ValueError(f"{case['id']} 的可见版本或可回答性与标注冲突")
    top_k = config['top_k']
    started = time.perf_counter()
    bm25 = lexical_search([corpus[ident] for ident in permitted], case['query'], config['bm25_candidates'])
    bm25_ms = (time.perf_counter() - started) * 1000
    vector_capture = case.get('vector') or {}
    vector_active = vector_capture.get('status') == 'ACTIVE'
    vector_ids = list(dict.fromkeys(vector_capture.get('ids', []))) if vector_active else []
    vector = [ident for ident in vector_ids if ident in permitted][:config['vector_candidates']]
    threshold = config.get('fusion_min_score')
    hybrid = [item['chunk_id'] for item in reciprocal_rank_fusion([bm25, vector])
              if threshold is None or item['score'] >= threshold] if vector else bm25
    rerank_captures = case.get('rerank') or {}
    variants = [
        ('BM25', bm25, False, False), ('VECTOR', vector, True, False),
        ('RRF', hybrid, True, False), ('RRF_RERANK', hybrid, True, bool(vector)),
        ('BM25_RERANK', bm25, False, True),
    ]
    ideal_dcg = sum(1 / math.log2(index + 2) for index in range(min(len(relevant), top_k)))
    results = {}
    for name, ranking, uses_vector, uses_rerank in variants:
        capture = rerank_captures.get(name) if uses_rerank and ranking else None
        final, ranked = replay_rerank(ranking, capture, config['rerank_window'], config.get('rerank_min_score'))
        hits = final[:top_k]
        positions = [index + 1 for index, ident in enumerate(hits) if ident in relevant]
        answer = (case.get('answers') or {}).get(name)
        citations = set(answer.get('citations', [])) if answer else set()
        supported = set(answer.get('supported_citations', [])) if answer else set()
        if supported - citations:
            raise ValueError(f"{case['id']} 的支持性标注含未引用片段")
        stages = ([vector_capture] if uses_vector else []) + ([capture or {}] if uses_rerank else [])
        effective = ('RERANK' if ranked else 'RRF' if name.startswith('RRF') and vector else
                     'VECTOR' if name == 'VECTOR' and vector else 'NONE' if name == 'VECTOR' else 'BM25')
        results[name] = {
            'effective': effective, 'candidate_count': len(ranking), 'hits': hits,
            'relevant_ranks_before': {ident: ranking.index(ident) + 1 for ident in sorted(relevant & set(ranking))},
            'relevant_ranks_after': {ident: final.index(ident) + 1 for ident in sorted(relevant & set(final))},
            'candidate_recall': len(relevant & set(ranking)) / len(relevant) if relevant else None,
            'recall': len(positions) / len(relevant) if relevant else None,
            'rr': (1 / positions[0] if positions else 0) if relevant else None,
            'ndcg': sum(1 / math.log2(position + 1) for position in positions) / ideal_dcg if ideal_dcg else None,
            'no_answer_has_hits': bool(hits) if not relevant else None,
            'unauthorized_candidates_filtered': len(set(vector_ids) - permitted) if uses_vector else 0,
            'unauthorized_sources': len((set(hits) | citations) - permitted),
            'citation_support': len(supported) / len(citations) if citations and 'supported_citations' in answer else None,
            'unanswerable_answered': bool(answer['answered']) if answer and not relevant else None,
            'downgraded': (uses_vector and not vector) or (uses_rerank and bool(ranking) and not ranked),
            'latency_ms': (bm25_ms if name != 'VECTOR' else 0) + sum(stage['duration_ms'] for stage in stages)
            if all(stage.get('duration_ms') is not None for stage in stages) else None,
            'model_calls': sum(stage['model_calls'] for stage in stages)
            if all(stage.get('model_calls') is not None for stage in stages) else None,
            'cost': sum(stage['cost'] for stage in stages) if all(stage.get('cost') is not None for stage in stages) else None,
        }
    return {'id': case['id'], 'project_id': case['project_id'], 'agent_id': case['agent_id'], 'variants': results}


def summarize(cases):
    """汇总有观测值的指标，保留样本量与相对 BM25 的同题差值。"""
    summary = {}
    for variant in cases[0]['variants']:
        values = [case['variants'][variant] for case in cases]
        stats = {'questions': len(values)}
        for key in ('candidate_recall', 'recall', 'rr', 'ndcg', 'no_answer_has_hits', 'citation_support',
                    'unanswerable_answered', 'downgraded', 'model_calls', 'cost'):
            observed = [row[key] for row in values if row[key] is not None]
            stats[key] = {'mean': statistics.mean(observed) if observed else None, 'n': len(observed)}
        delta = [row['rr'] - case['variants']['BM25']['rr'] for row, case in zip(values, cases)
                 if row['rr'] is not None]
        latency = sorted(row['latency_ms'] for row in values if row['latency_ms'] is not None)
        stats.update({
            'no_hit_rate': statistics.mean(not row['hits'] for row in values),
            'mrr_delta_vs_bm25': statistics.mean(delta) if delta else None,
            'unauthorized_sources': sum(row['unauthorized_sources'] for row in values),
            'p50_ms': statistics.median(latency) if latency else None,
            'p95_ms': latency[math.ceil(len(latency) * .95) - 1] if latency else None,
            'latency_n': len(latency),
        })
        summary[variant] = stats
    return summary


def main():
    """读取标注 JSON，写出无正文的评测结果并让越权来源检测返回非零。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.dataset.read_text(encoding='utf-8'))
        config = data['config']
        if not 1 <= config['top_k'] <= 50 or any(not 1 <= config[key] <= 5000 for key in (
            'bm25_candidates', 'vector_candidates', 'rerank_window',
        )):
            raise ValueError('Top-K 或候选窗口超出范围')
        corpus = {row['id']: SimpleNamespace(position=0, **row) if 'position' not in row else SimpleNamespace(**row)
                  for row in data['chunks']}
        if not corpus or len(corpus) != len(data['chunks']) or not data['cases']:
            raise ValueError('语料或题目为空，或片段 ID 重复')
        cases = [evaluate_case(case, corpus, config) for case in data['cases']]
        distinct = {(row.project_id, row.version_id, row.text) for row in corpus.values()}
        summary = summarize(cases)
        report = {'dataset': data['dataset'], 'config': config, 'duplicate_chunk_rate': 1 - len(distinct) / len(corpus),
                  'summary': summary, 'cases': cases}
        output = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
        if args.output:
            args.output.write_text(output, encoding='utf-8')
        else:
            print(output, end='')
        return 1 if any(row['unauthorized_sources'] for row in summary.values()) else 0
    except (OSError, KeyError, TypeError, ValueError) as error:
        parser.exit(2, f'评测失败：{error}\n')


if __name__ == '__main__':
    sys.exit(main())
