"""User-managed Agent sessions are recoverable; task sessions remain protected evidence."""

from tests.conftest import unique


def test_agent_session_batch_delete_preserves_message_history_and_restores_same_id(api, admin, db):
    from app.agents.models.message import AgentMessage
    from app.agents.models.session import AgentSession

    project = api.post("/projects", username=admin, json={"name": unique("session-trash-project")}).json()
    project_id = project["id"]
    session = api.post(f"/projects/{project_id}/agent/sessions", username=admin, json={}).json()
    session_id = session["id"]
    db.add(AgentMessage(session_id=session_id, role="USER", content="保留的会话消息"))
    db.commit()

    receipt = api.post(
        "/resources/agent_session/batch-delete", username=admin,
        json={"project_id": project_id, "ids": [session_id, -1]},
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["succeeded"] == 1
    assert receipt.json()["failed"] == 1
    assert api.get(f"/agent/sessions/{session_id}", username=admin).status_code == 404
    assert api.delete(f"/agent/sessions/{session_id}", username=admin).status_code == 204

    deleted = db.query(AgentSession).execution_options(include_deleted=True).filter_by(id=session_id).one()
    assert deleted.deleted_at is not None
    assert db.query(AgentMessage).filter_by(session_id=session_id).count() == 1

    item = next(
        row for row in api.get(f"/recycle-bin?project_id={project_id}&resource_type=agent_session", username=admin).json()["items"]
        if row["resource_id"] == str(session_id)
    )
    preview = api.get(f"/recycle-bin/{item['id']}/purge-preview", username=admin).json()
    assert preview["allowed"] is False
    assert any("agent_message.session_id" in dependency for dependency in preview["dependencies"])

    restored = api.post(f"/recycle-bin/{item['id']}/restore", username=admin)
    assert restored.status_code == 200, restored.text
    detail = api.get(f"/agent/sessions/{session_id}", username=admin)
    assert detail.status_code == 200, detail.text
    assert detail.json()["session"]["id"] == session_id
    assert detail.json()["messages"][0]["content"] == "保留的会话消息"
