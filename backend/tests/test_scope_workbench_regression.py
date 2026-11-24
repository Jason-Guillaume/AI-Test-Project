"""Scope workbench totals, isolation, and request/SQL measurements."""
from time import perf_counter
from sqlalchemy import event
from tests.test_47_test_scope import _project, _case, _register
from tests.conftest import unique


def test_scope_totals_deduplicate_and_hide_deleted(api, admin):
    project = _project(api, admin)
    parent = api.post(f'/projects/{project}/test-scopes', username=admin, json={'direction':'API', 'node_type':'FOLDER', 'name':unique('parent')}).json()
    children = [api.post(f'/projects/{project}/test-scopes', username=admin, json={'direction':'API', 'node_type':'FOLDER', 'parent_id':parent['id'], 'name':unique('child')}).json() for _ in range(2)]
    case = _case(api, admin, project, unique('same'), priority='P0')
    assert api.put(f"/test-cases/{case['id']}/scope-links", username=admin, json={'scope_node_ids':[x['id'] for x in children]}).status_code == 200
    path = f'/projects/{project}/test-scope-cases'
    total = api.get(path, username=admin, params={'direction':'API'}).json()
    stats = api.get(f'/projects/{project}/test-scopes/stats', username=admin, params={'direction':'API'}).json()
    assert total['total'] == stats['case_count'] == 1
    assert api.get(path, username=admin, params={'scope_node_id':parent['id'], 'direction':'API'}).json()['total'] == 1
    assert api.get(path, username=admin, params={'direction':'API', 'keyword':f"#{case['id']}"}).json()['total'] == 1
    assert api.get(path, username=admin, params={'direction':'UI', 'keyword':f"#{case['id']}"}).json()['total'] == 0
    outsider = unique('outsider'); _register(api, outsider)
    assert api.get(path, username=outsider, params={'direction':'API', 'keyword':str(case['id'])}).status_code == 404
    assert api.delete(f"/test-cases/{case['id']}", username=admin).status_code == 204
    assert api.get(path, username=admin, params={'direction':'API'}).json()['total'] == 0
    assert api.get(f'/projects/{project}/test-scopes/stats', username=admin, params={'direction':'API'}).json()['case_count'] == 0
    tree = api.get(f'/projects/{project}/test-scopes', username=admin, params={'direction':'API'}).json()
    assert next(x for x in tree['items'] if x['id'] == parent['id'])['case_count'] == 0


def test_scope_request_measurement(api, admin, db):
    project = _project(api, admin)
    nodes = [api.post(f'/projects/{project}/test-scopes', username=admin, json={'direction':'API', 'node_type':'FOLDER', 'name':unique('perf')}).json()['id'] for _ in range(10)]
    for i in range(30):
        case = _case(api, admin, project, unique('perf-case'))
        assert api.post(f'/projects/{project}/test-scope-cases/move', username=admin, json={'case_ids':[case['id']], 'scope_node_id':nodes[i % 10]}).status_code == 200
    tree = f'/projects/{project}/test-scopes'; stats = tree + '/stats'; listing = f'/projects/{project}/test-scope-cases'
    def measure(old):
        count = 0
        def before(*args):
            nonlocal count
            count += 1
        event.listen(db.bind, 'before_cursor_execute', before)
        start = perf_counter(); requests = 0
        def get(url, params=None):
            nonlocal requests
            requests += 1
            response = api.get(url, username=admin, params=params)
            assert response.status_code == 200, response.text
        try:
            get(tree, {'direction':'API'}); get(stats, {'direction':'API'})
            if old: get(f'/test-scopes/{nodes[0]}')
            get(listing, {'direction':'API', **({'scope_node_id':nodes[0]} if old else {})})
            first = (requests, count, (perf_counter() - start) * 1000)
            requests = count = 0; start = perf_counter()
            for node in nodes:
                if old: get(f'/test-scopes/{node}')
                get(listing, {'direction':'API', 'scope_node_id':node})
            return first, (requests, count, (perf_counter() - start) * 1000)
        finally:
            event.remove(db.bind, 'before_cursor_execute', before)
    old, new = measure(True), measure(False)
    print(f'PERF 30 cases, 10 directories: before first={old[0]}, switches={old[1]}; after first={new[0]}, switches={new[1]}')
    assert new[0][0] < old[0][0] and new[1][0] < old[1][0]


def test_create_case_target_is_atomic_and_direction_checked(api, admin):
    project = _project(api, admin)
    node = api.post(f'/projects/{project}/test-scopes', username=admin, json={'direction':'API', 'node_type':'FOLDER', 'name':unique('target')}).json()
    created = api.post(f'/projects/{project}/test-cases', username=admin, json={'name':unique('explicit'), 'target_type':'API', 'scope_node_id':node['id']})
    assert created.status_code == 201, created.text
    listing = api.get(f'/projects/{project}/test-scope-cases', username=admin, params={'scope_node_id':node['id'], 'direction':'API', 'sort':'priority', 'order':'asc'})
    assert listing.status_code == 200, listing.text
    assert [item['id'] for item in listing.json()['items']] == [created.json()['id']]
    rejected = api.post(f'/projects/{project}/test-cases', username=admin, json={'name':unique('wrong-direction'), 'target_type':'WEB', 'scope_node_id':node['id']})
    assert rejected.status_code == 400
