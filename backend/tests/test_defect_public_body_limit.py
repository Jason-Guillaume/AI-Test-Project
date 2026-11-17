import asyncio

from app.features.defects.public_body_limit import PublicShareBodyLimit


def run_request(chunks, path='/api/v1/public/defect-shares/example/resolve'):
    called = []
    sent = []
    messages = iter([
        {'type': 'http.request', 'body': chunk, 'more_body': i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ])

    async def receive():
        return next(messages)

    async def send(message):
        sent.append(message)

    async def app(scope, receive, send):
        called.append((await receive())['body'])

    scope = {'type': 'http', 'method': 'POST', 'path': path, 'headers': []}
    asyncio.run(PublicShareBodyLimit(app, limit=16)(scope, receive, send))
    return called, sent


def test_chunked_body_over_limit_is_rejected_without_content_length():
    called, sent = run_request([b'a' * 10, b'b' * 7])
    assert not called
    assert sent[0]['status'] == 413
    assert (b'cache-control', b'no-store') in sent[0]['headers']


def test_body_at_limit_is_replayed_to_application():
    called, sent = run_request([b'a' * 10, b'b' * 6])
    assert called == [b'a' * 10 + b'b' * 6]
    assert not sent


def test_other_routes_are_not_restricted():
    called, _ = run_request([b'a' * 17], '/api/v1/other')
    assert called == [b'a' * 17]
