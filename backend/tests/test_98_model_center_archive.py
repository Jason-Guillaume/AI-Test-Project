"""Model-center archive API keeps model history and enforces admin access."""
from tests.conftest import unique


def test_archive_and_restore_embedding_resource(api, admin):
    username = unique('model-member')
    assert api.register(username).status_code == 201
    api.login(username)
    response = api.post('/model-center/resources', username=admin, json={
        'category': 'EMBEDDING', 'visibility': 'PLATFORM', 'display_name': unique('embedding'),
        'provider': 'fixture', 'adapter_key': 'openai-compatible-embeddings', 'model_name': 'fixture',
        'endpoint': 'https://fixture.invalid/embedding', 'config': {}, 'capabilities': ['embedding'],
    })
    assert response.status_code == 201, response.text
    ident = response.json()['id']
    assert api.delete(f'/model-center/resources/{ident}', username=username).status_code == 403
    assert api.delete(f'/model-center/resources/{ident}', username=admin).status_code == 204
    live = api.get('/model-center/resources?category=EMBEDDING', username=admin)
    assert ident not in [row['id'] for row in live.json()['items']]
    deleted = api.get('/model-center/resources?category=EMBEDDING&archived=true', username=admin)
    assert ident in [row['id'] for row in deleted.json()['items']]
    assert api.put(f'/model-center/resources/{ident}/enabled?enabled=true', username=admin).status_code == 400
    restored = api.post(f'/model-center/resources/{ident}/restore', username=admin)
    assert restored.status_code == 200 and restored.json()['status'] == 'DISABLED'
    assert api.put(f'/model-center/resources/{ident}/enabled?enabled=true', username=admin).status_code == 200
