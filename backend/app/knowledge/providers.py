"""Retrieval model protocols. Connections and encoding rules are supplied by configuration."""
from __future__ import annotations

import math
import json
from dataclasses import dataclass

import httpx


class RetrievalProviderError(ValueError):
    """The retrieval endpoint returned an invalid or unusable response."""


@dataclass(frozen=True)
class RetrievalConnection:
    endpoint: str
    model: str
    credential: str
    timeout: float
    credential_header: str = 'Authorization'


def _post(connection: RetrievalConnection, payload: dict, *, transport=None) -> dict:
    headers = {'Content-Type': 'application/json'}
    if connection.credential:
        headers[connection.credential_header] = (
            f'Bearer {connection.credential}' if connection.credential_header.lower() == 'authorization'
            else connection.credential
        )
    try:
        with httpx.Client(timeout=connection.timeout, transport=transport, follow_redirects=False, trust_env=False) as client:
            with client.stream('POST', connection.endpoint, json=payload, headers=headers) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > 8_000_000:
                        raise RetrievalProviderError('retrieval response too large')
                data = json.loads(body)
    except (httpx.HTTPError, ValueError) as exc:
        raise RetrievalProviderError('retrieval endpoint failed') from exc
    if not isinstance(data, dict):
        raise RetrievalProviderError('invalid response')
    return data


def embed(connection: RetrievalConnection, texts: list[str], dimension: int, *,
          input_type: str | None = None, transport=None) -> list[list[float]]:
    """OpenAI-compatible embedding response, reordered and checked against the index generation."""
    if not texts:
        return []
    if dimension < 1:
        raise RetrievalProviderError('invalid dimension')
    payload = {'model': connection.model, 'input': texts}
    if input_type:
        payload['input_type'] = input_type
    data = _post(connection, payload, transport=transport).get('data')
    if not isinstance(data, list) or len(data) != len(texts):
        raise RetrievalProviderError('invalid embedding count')
    indexed = {}
    for item in data:
        if not isinstance(item, dict):
            raise RetrievalProviderError('invalid embedding item')
        index, vector = item.get('index'), item.get('embedding')
        if isinstance(index, bool) or not isinstance(index, int) or index not in range(len(texts)) or index in indexed:
            raise RetrievalProviderError('invalid embedding index')
        if not isinstance(vector, list) or len(vector) != dimension or any(
            isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in vector
        ):
            raise RetrievalProviderError('invalid embedding dimension or value')
        indexed[index] = [float(v) for v in vector]
    return [indexed[i] for i in range(len(texts))]


def rerank(connection: RetrievalConnection, query: str, documents: list[str], *, transport=None) -> list[tuple[int, float]]:
    """Return a complete permutation; malformed or partial rankings must fall back to RRF."""
    if not documents:
        return []
    results = _post(connection, {'model': connection.model, 'query': query, 'documents': documents,
                                'top_n': len(documents)}, transport=transport).get('results')
    if not isinstance(results, list) or len(results) != len(documents):
        raise RetrievalProviderError('invalid rerank count')
    ranking = []
    seen = set()
    for item in results:
        if not isinstance(item, dict):
            raise RetrievalProviderError('invalid rerank item')
        index, score = item.get('index'), item.get('relevance_score')
        if (isinstance(index, bool) or not isinstance(index, int) or index not in range(len(documents))
                or index in seen or isinstance(score, bool) or not isinstance(score, (int, float))
                or not math.isfinite(score)):
            raise RetrievalProviderError('invalid rerank index or score')
        seen.add(index)
        ranking.append((index, float(score)))
    return ranking
