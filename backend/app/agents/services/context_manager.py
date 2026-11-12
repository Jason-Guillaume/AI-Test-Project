"""Agent 上下文装配：按会话权限、来源引用和 Token 预算挑选历史消息。"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class ContextMessage:
    """带有可追溯来源和权限范围的上下文消息。"""

    message_id: int
    role: str
    message_type: str
    content: str
    created_at: datetime | None


def estimate_tokens(text: str) -> int:
    """用保守字符权重估算上下文 Token，避免依赖指定供应商的 tokenizer。"""
    cost = sum(1.0 if ord(char) >= 0x3400 else 0.25 if char.isalnum() else 0.5 for char in text)
    return max(1, math.ceil(cost)) if text else 0


def _query_terms(text: str) -> set[str]:
    """生成中英文混合检索词，用于召回较早但相关的会话消息。"""
    terms: set[str] = set()
    for token in re.findall(r'[a-zA-Z0-9_]+|[\u3400-\u9fff]+', text.lower()):
        if token[0].isascii():
            terms.add(token)
        elif len(token) > 1:
            terms.update(token[index:index + 2] for index in range(len(token) - 1))
        else:
            terms.add(token)
    return terms


def _relevance(message: ContextMessage, terms: set[str], age: int) -> float:
    """按查询词覆盖度和时间新近度排序，近期消息获得稳定保留权重。"""
    content_terms = _query_terms(message.content)
    overlap = len(content_terms & terms) / max(1, len(terms))
    return overlap + 0.2 / (age + 1)


def assemble_history(
    *,
    session: Any,
    messages: list[Any],
    query: str | None,
    token_budget: int,
    max_messages: int = 8,
    total_message_count: int | None = None,
    summary: dict[str, Any] | None = None,
    long_term_memories: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """选取当前 AgentSession 的最近与相关历史，并生成本次装配清单。"""
    sources = [
        ContextMessage(
            message_id=message.id,
            role=message.role.lower(),
            message_type=message.message_type,
            content=message.content,
            created_at=message.created_at,
        )
        for message in messages if message.content
    ]
    terms = _query_terms(query or '')
    budget = max(0, int(token_budget))
    count_limit = max(0, int(max_messages))
    latest = sources[-1:] if sources else []
    latest_user = next((source for source in reversed(sources) if source.role == 'user'), None)
    priority = []
    for source in (latest_user, latest[0] if latest else None):
        if source is not None and source not in priority:
            priority.append(source)
    priority_ids = {source.message_id for source in priority}
    historical = [source for source in sources if source.message_id not in priority_ids]
    ranked = sorted(
        enumerate(historical),
        key=lambda item: (_relevance(item[1], terms, len(historical) - item[0]), item[0]),
        reverse=True,
    )
    selected: list[ContextMessage] = []
    used = 0
    truncated_ids: list[int] = []

    def append_with_budget(source: ContextMessage) -> None:
        nonlocal used
        remaining = budget - used
        cost = estimate_tokens(source.content)
        if cost > remaining:
            if remaining <= 0:
                return
            marker = '…[较早内容已截断]…'
            low, high = 0, len(source.content)
            while low < high:
                middle = (low + high + 1) // 2
                candidate = marker + source.content[-middle:] if middle else marker
                if estimate_tokens(candidate) <= remaining:
                    low = middle
                else:
                    high = middle - 1
            clipped = marker + source.content[-low:] if low else source.content[-remaining * 2:]
            source = ContextMessage(source.message_id, source.role, source.message_type, clipped, source.created_at)
            cost = estimate_tokens(clipped)
            if cost > remaining:
                # 对极小预算，不带标记保留消息尾部；字符估算与 Token 成本同口径。
                low, high = 0, len(source.content)
                while low < high:
                    middle = (low + high + 1) // 2
                    if estimate_tokens(source.content[-middle:]) <= remaining:
                        low = middle
                    else:
                        high = middle - 1
                if low == 0:
                    return
                source = ContextMessage(source.message_id, source.role, source.message_type,
                                        source.content[-low:], source.created_at)
                cost = estimate_tokens(source.content)
            truncated_ids.append(source.message_id)
        if cost <= remaining:
            selected.append(source)
            used += cost

    latest_user_source = next((source for source in priority if source.role == 'user'), None)
    if latest_user_source is not None and count_limit:
        append_with_budget(latest_user_source)

    context_preamble: list[dict[str, str]] = []
    memory_refs: list[dict[str, Any]] = []
    memory_token_count = 0
    memory_items = long_term_memories or []
    memory_text = "\n".join(
        f"[{item['memory_key']}@v{item['version']}] {item['content'][:1000]}"
        for item in memory_items
    )
    if memory_text and len(selected) + len(context_preamble) < count_limit:
        memory_content = "以下是同一项目、同一 Agent 的长期记忆记录（保留原始来源指纹）：\n" + memory_text
        memory_cost = estimate_tokens(memory_content)
        if memory_cost <= budget - used:
            context_preamble.append({'role': 'user', 'content': memory_content})
            used += memory_cost
            memory_token_count = memory_cost
            memory_refs = [
                {'id': item['id'], 'memory_key': item['memory_key'], 'version': item['version'],
                 'source_digest': item['source_digest'], 'source_refs': item['source_refs']}
                for item in memory_items
            ]

    summary_used = False
    summary_token_count = 0
    summary_source_refs = summary.get('source_refs', []) if summary else []
    summary_terms = _query_terms(summary.get('text', '')) if summary else set()
    if (
        summary and summary.get('text') and len(selected) + len(context_preamble) < count_limit
        and (not terms or bool(terms & summary_terms))
    ):
        candidate_summary = (
            '以下是同一 Agent 会话的历史原文摘录，仅作上下文参考：\n'
            + summary['text']
        )
        candidate_cost = estimate_tokens(candidate_summary)
        if candidate_cost <= budget - used:
            summary_token_count = candidate_cost
            used += candidate_cost
            summary_used = True
            context_preamble.append({'role': 'user', 'content': candidate_summary})

    for source in priority:
        if source is latest_user_source:
            continue
        if len(selected) + len(context_preamble) >= count_limit:
            break
        append_with_budget(source)
    for _, source in ranked:
        if len(selected) + len(context_preamble) >= count_limit:
            break
        append_with_budget(source)
    selected.sort(key=lambda source: source.message_id)
    manifest = {
        'version': 'agent-context-selection-v3',
        'permission_scope': {
            'project_id': session.project_id,
            'agent_session_id': session.id,
            'agent_run_id': session.task_agent_instance_id,
        },
        'query_sha256': hashlib.sha256((query or '').encode('utf-8')).hexdigest(),
        'token_budget': budget,
        'estimated_tokens': used,
        'truncated_message_ids': truncated_ids,
        'source_refs': [
            {'kind': 'AGENT_MESSAGE', 'id': source.message_id,
             'version': source.message_id, 'message_type': source.message_type}
            for source in selected
        ],
        'candidate_message_count': len(sources),
        'unsearched_message_count': max(0, (total_message_count or len(sources)) - len(sources)),
        'omitted_message_count': max(0, (total_message_count or len(sources)) - len(selected)),
        'summary_used': summary_used,
        'summary_version': summary.get('version') if summary_used and summary else None,
        'summary_source_count': len(summary_source_refs) if summary_used else 0,
        'summary_token_count': summary_token_count,
        'summary_source_digest': summary.get('source_digest') if summary_used and summary else None,
        'summary_source_refs': [
            {'kind': 'AGENT_MESSAGE', 'id': source['message_id'],
             'version': source['content_sha256'], 'message_type': source['message_type']}
            for source in summary_source_refs
        ] if summary_used else [],
        'memory_count': len(memory_refs),
        'memory_ids': [item['id'] for item in memory_refs],
        'memory_refs': memory_refs,
        'memory_token_count': memory_token_count,
    }
    assembled = [{'role': source.role, 'content': source.content} for source in selected]
    return context_preamble + assembled, manifest
