"""Lifecycle coverage for project security strategies and mutation rules."""

from uuid import uuid4

from tests.conftest import unique


def _project(api, admin):
    response = api.post(
        "/projects", username=admin,
        json={"name": unique("security-trash"), "description": "lifecycle"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _strategy(api, admin, project_id, *, key=None, include_rule=True):
    key = key or f"TRASH_{uuid4().hex[:10].upper()}"
    body = {
        "name": f"策略-{key}", "strategy_key": key, "category": "AUTHENTICATION",
        "enabled": True, "risk_level": "MEDIUM",
        "rules": ([{
            "name": "规则 A", "mutation_type": "REMOVE_TOKEN", "target_location": "HEADER",
            "target_field": "Authorization", "mutation_config": {},
            "expected_security_behavior": "EXPECTED_DENY", "expected_status_codes": [401, 403],
            "severity": "MEDIUM", "enabled": True,
        }] if include_rule else []),
    }
    response = api.post(
        f"/projects/{project_id}/security-strategies", username=admin, json=body,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_security_strategy_delete_recycles_strategy_and_rule(api, admin):
    project_id = _project(api, admin)
    strategy = _strategy(api, admin, project_id)
    rule_id = strategy["rules"][0]["id"]

    deleted = api.delete(f"/security-strategies/{strategy['id']}", username=admin)
    assert deleted.status_code == 204, deleted.text
    assert api.get(f"/security-strategies/{strategy['id']}", username=admin).status_code == 404
    response = api.get(
        f"/recycle-bin?project_id={project_id}", username=admin,
    )
    assert response.status_code == 200, response.text
    resources = {(item["resource_type"], item["resource_id"]) for item in response.json()["items"]}
    assert ("security_strategy", str(strategy["id"])) in resources
    assert ("security_rule", str(rule_id)) in resources

    selected = [item["id"] for item in response.json()["items"]
                if item["resource_type"] in {"security_strategy", "security_rule"}]
    restored = api.post("/recycle-bin/batch-restore", username=admin, json={"item_ids": selected})
    assert restored.status_code == 200, restored.text
    assert restored.json()["succeeded"] == 2
    assert api.get(f"/security-strategies/{strategy['id']}", username=admin).status_code == 200


def test_security_rule_batch_delete_and_restore_keeps_history(api, admin, db):
    from app.features.security_testing.models import SecurityMutationRule

    project_id = _project(api, admin)
    strategy = _strategy(api, admin, project_id)
    rule_id = strategy["rules"][0]["id"]

    deleted = api.post(
        "/resources/security_rule/batch-delete", username=admin,
        json={"project_id": project_id, "ids": [rule_id]},
    )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["succeeded"] == 1
    deleted_rule = db.query(SecurityMutationRule).execution_options(include_deleted=True).filter_by(id=rule_id).one()
    assert deleted_rule.deleted_at is not None
    assert api.get(f"/security-strategies/{strategy['id']}", username=admin).json()["rules"] == []

    item = api.get(
        f"/recycle-bin?project_id={project_id}&resource_type=security_rule", username=admin,
    ).json()["items"][0]
    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    assert api.get(f"/security-strategies/{strategy['id']}", username=admin).json()["rules"][0]["id"] == rule_id


def test_security_strategy_restore_key_conflict_keeps_original(api, admin):
    project_id = _project(api, admin)
    key = f"TRASH_{uuid4().hex[:10].upper()}"
    original = _strategy(api, admin, project_id, key=key, include_rule=False)
    assert api.delete(f"/security-strategies/{original['id']}", username=admin).status_code == 204

    replacement = _strategy(api, admin, project_id, key=key, include_rule=False)
    item = api.get(
        f"/recycle-bin?project_id={project_id}&resource_type=security_strategy", username=admin,
    ).json()["items"][0]
    restore = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restore.status_code == 409
    assert api.get(f"/security-strategies/{original['id']}", username=admin).status_code == 404
    assert api.get(f"/security-strategies/{replacement['id']}", username=admin).status_code == 200

    assert api.delete(f"/security-strategies/{replacement['id']}", username=admin).status_code == 204
    replacement_item = api.get(
        f"/recycle-bin?project_id={project_id}&resource_type=security_strategy", username=admin,
    ).json()["items"][0]
    preview = api.get(f"/recycle-bin/{replacement_item['id']}/purge-preview", username=admin)
    assert preview.status_code == 200 and preview.json()["allowed"] is True, preview.text
    purge = api.client.request(
        "DELETE", f"/api/v1/recycle-bin/{replacement_item['id']}/permanent",
        headers=api.headers(admin),
        json={"confirmation": "PERMANENTLY_DELETE", "reason": "isolated lifecycle test cleanup"},
    )
    assert purge.status_code == 200, purge.text
    assert api.post(f"/recycle-bin/{item['id']}/restore", username=admin).status_code == 200


def test_security_rule_delete_cannot_cross_project(api, admin):
    project_a = _project(api, admin)
    project_b = _project(api, admin)
    strategy = _strategy(api, admin, project_a)
    rule_id = strategy["rules"][0]["id"]
    response = api.post(
        "/resources/security_rule/batch-delete", username=admin,
        json={"project_id": project_b, "ids": [rule_id]},
    )
    assert response.status_code == 200
    assert response.json()["failed"] == 1
    assert api.get(f"/security-strategies/{strategy['id']}", username=admin).json()["rules"]
