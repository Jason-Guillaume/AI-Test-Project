"""任务内浏览器会话绑定校验与 Web UI 权限门禁。"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.agents.browser_authoring.services import session_service as web_session_service
from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskRun
from app.orchestration.tasks.services.web_session_binding import validate_task_web_session_binding


class FakeDB:
    def __init__(self, objects):
        self.objects = objects
        self.queries = []

    def get(self, model, item_id):
        return self.objects.get((model, item_id))

    def query(self, model):
        query = FakeQuery(model)
        self.queries.append(query)
        return query


class FakeQuery:
    def __init__(self, model):
        self.model = model
        self.criteria = ()
        self.row = None

    def filter(self, *criteria):
        self.criteria = criteria
        return self

    def order_by(self, *_ordering):
        return self

    def first(self):
        return self.row


def valid_binding():
    run = SimpleNamespace(
        id=12,
        task_id=5,
        status="WAITING_CONFIRMATION",
        input_snapshot={"target_type": "WEB_AUTHORING", "environment_id": 17},
    )
    return FakeDB({
        (TaskRun, 12): run,
        (Task, 5): SimpleNamespace(id=5, project_id=9),
        (TaskAgentInstance, 21): SimpleNamespace(id=21, task_run_id=12, role="UI_WORKER"),
    })


def test_task_web_binding_accepts_matching_project_run_environment_and_worker():
    validate_task_web_session_binding(
        valid_binding(),
        project_id=9,
        environment_id=17,
        task_run_id=12,
        task_agent_instance_id=21,
    )


@pytest.mark.parametrize(
    "failure",
    ["missing_run", "missing_task", "wrong_project", "wrong_target", "terminal_run", "wrong_environment", "missing_worker", "wrong_worker_run", "wrong_worker_role"],
)
def test_task_web_binding_rejects_mismatched_run_or_participant(failure):
    db = valid_binding()
    if failure == "missing_run":
        db.objects.pop((TaskRun, 12))
    elif failure == "missing_task":
        db.objects.pop((Task, 5))
    elif failure == "wrong_project":
        db.objects[(Task, 5)].project_id = 10
    elif failure == "wrong_target":
        db.objects[(TaskRun, 12)].input_snapshot["target_type"] = "TEST_EXECUTION"
    elif failure == "terminal_run":
        db.objects[(TaskRun, 12)].status = "COMPLETED"
    elif failure == "wrong_environment":
        db.objects[(TaskRun, 12)].input_snapshot["environment_id"] = 18
    elif failure == "missing_worker":
        db.objects.pop((TaskAgentInstance, 21))
    elif failure == "wrong_worker_run":
        db.objects[(TaskAgentInstance, 21)].task_run_id = 13
    elif failure == "wrong_worker_role":
        db.objects[(TaskAgentInstance, 21)].role = "MAIN"

    with pytest.raises(HTTPException) as error:
        validate_task_web_session_binding(
            db,
            project_id=9,
            environment_id=17,
            task_run_id=12,
            task_agent_instance_id=21,
        )
    assert error.value.status_code == 404
    assert error.value.detail == "任务 Web 工作区不存在"


def test_web_ui_requires_validator_for_task_bound_session(monkeypatch):
    monkeypatch.setattr(web_session_service, "require_writable_project", lambda *_args: None)
    monkeypatch.setattr(web_session_service, "resolve_project_environment", lambda *_args: SimpleNamespace(id=17))

    with pytest.raises(HTTPException) as error:
        web_session_service.start_session(
            object(),
            9,
            SimpleNamespace(environment_id=17),
            object(),
            task_run_id=12,
            task_agent_instance_id=21,
        )
    assert error.value.status_code == 404
    assert error.value.detail == "任务 Web 工作区不存在"


def test_web_ui_keeps_project_write_gate_before_task_validator(monkeypatch):
    project_denied = HTTPException(status_code=403, detail="项目无写权限")
    called = []

    def deny_project(*_args):
        raise project_denied

    monkeypatch.setattr(web_session_service, "require_writable_project", deny_project)
    monkeypatch.setattr(
        web_session_service,
        "resolve_project_environment",
        lambda *_args: pytest.fail("环境解析不能越过项目权限门禁"),
    )

    with pytest.raises(HTTPException) as error:
        web_session_service.start_session(
            object(),
            9,
            SimpleNamespace(environment_id=17),
            object(),
            task_run_id=12,
            task_agent_instance_id=21,
            task_binding_validator=lambda *_args, **_kwargs: called.append(True),
        )
    assert error.value is project_denied
    assert called == []


def test_web_ui_reuses_active_session_for_validated_task_run(monkeypatch):
    from app.features.web_testing.models import WebAgentSession
    from app.execution.browser.session_manager import registry

    db = valid_binding()
    prior = SimpleNamespace(id=44, status="ACTIVE")
    query = FakeQuery(WebAgentSession)
    query.row = prior
    db.query = lambda model: query
    validator_calls = []
    expected_response = {"id": prior.id, "status": prior.status}

    monkeypatch.setattr(web_session_service, "require_writable_project", lambda *_args: None)
    monkeypatch.setattr(
        web_session_service,
        "resolve_project_environment",
        lambda *_args: SimpleNamespace(id=17),
    )
    monkeypatch.setattr(registry, "get_session", lambda session_id: object() if session_id == prior.id else None)
    monkeypatch.setattr(web_session_service, "session_response", lambda row: expected_response)

    result = web_session_service.start_session(
        db,
        9,
        SimpleNamespace(environment_id=17),
        object(),
        task_run_id=12,
        task_agent_instance_id=21,
        task_binding_validator=lambda *_args, **kwargs: validator_calls.append(kwargs),
    )

    assert result == expected_response
    assert validator_calls == [{
        "project_id": 9,
        "environment_id": 17,
        "task_run_id": 12,
        "task_agent_instance_id": 21,
    }]
    assert query.model is WebAgentSession
    assert len(query.criteria) == 1
    assert query.criteria[0].left.name == "task_run_id"
    assert query.criteria[0].left.table.name == WebAgentSession.__tablename__
    assert query.criteria[0].right.value == 12
