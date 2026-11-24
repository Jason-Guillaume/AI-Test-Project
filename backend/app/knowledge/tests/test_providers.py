import httpx
import pytest

from app.knowledge.providers import RetrievalConnection, RetrievalProviderError, embed, rerank


CONNECTION = RetrievalConnection('https://model.invalid/endpoint', 'configured-model', 'secret', 2)


def test_embedding_orders_vectors_and_passes_configured_input_mode():
    def handle(request):
        assert request.headers['authorization'] == 'Bearer secret'
        assert b'"input_type":"document"' in request.content
        return httpx.Response(200, json={'data': [{'index': 1, 'embedding': [3, 4]},
                                                  {'index': 0, 'embedding': [1, 2]}]})
    assert embed(CONNECTION, ['a', 'b'], 2, input_type='document', transport=httpx.MockTransport(handle)) == [[1, 2], [3, 4]]


@pytest.mark.parametrize('data', [
    [{'index': 0, 'embedding': [1]}],
    [{'index': 0, 'embedding': [1, float('nan')]}],
    [{'index': 1, 'embedding': [1, 2]}],
])
def test_embedding_rejects_invalid_output(data):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'data': data}))
    with pytest.raises((RetrievalProviderError, ValueError)):
        embed(CONNECTION, ['a'], 2, transport=transport)


def test_rerank_validates_positions_and_completeness():
    valid = httpx.MockTransport(lambda request: httpx.Response(200, json={'results': [
        {'index': 1, 'relevance_score': 0.9}, {'index': 0, 'relevance_score': 0.2}]}))
    assert rerank(CONNECTION, 'query', ['a', 'b'], transport=valid) == [(1, 0.9), (0, 0.2)]
    invalid = httpx.MockTransport(lambda request: httpx.Response(200, json={'results': [
        {'index': 0, 'relevance_score': 0.9}, {'index': 0, 'relevance_score': 0.2}]}))
    with pytest.raises(RetrievalProviderError):
        rerank(CONNECTION, 'query', ['a', 'b'], transport=invalid)


def test_provider_errors_do_not_expose_response_or_credentials():
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text='secret business text'))
    with pytest.raises(RetrievalProviderError) as error:
        embed(CONNECTION, ['private content'], 2, transport=transport)
    assert str(error.value) == 'retrieval endpoint failed'
