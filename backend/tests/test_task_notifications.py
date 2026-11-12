"""任务事件与个人收件箱在同一事务中提交。"""

import pytest
from fastapi import HTTPException

from app.orchestration.tasks.models import Task, TaskEvent, TaskResourceRef, TaskRun
from app.orchestration.tasks.services.task_service import TaskService
from app.orchestration.tasks.services.state_service import append_event
from app.platform.environment_configuration.services.environment_service import resolve_project_environment
from app.core.models.notification import Notification
from tests.conftest import unique
from tests.test_15_test_executor import _admin_id, _create_project, _make_env


def test_task_notification_commit_and_rollback(api, admin, db):
    project_id = _create_project(api, admin)
    user_id = _admin_id(db)
    task = Task(project_id=project_id, created_by=user_id, title="任务通知测试", goal="测试任务通知")
    db.add(task)
    db.flush()
    run = TaskRun(task_id=task.id, created_by=user_id, run_number=1, goal_snapshot=task.goal, input_snapshot={})
    db.add(run)
    db.commit()

    append_event(db, run, "plan.proposed", {"version": 1})
    db.commit()
    notice = db.query(Notification).filter_by(user_id=user_id, event_type="task.plan_ready", project_id=project_id).one()
    assert notice.payload["detail"] == {"task_id": task.id, "run_id": run.id}
    response = api.get("/notifications", username=admin, params={"event_type": "task.plan_ready", "project_id": project_id})
    assert response.status_code == 200
    assert any(item["id"] == notice.id for item in response.json()["items"])

    append_event(db, run, "run.completed", {"status": "SUCCEEDED"})
    db.flush()
    db.rollback()
    assert db.query(Notification).filter_by(user_id=user_id, event_type="task.completed", project_id=project_id).count() == 0
    assert db.query(TaskEvent).filter_by(task_run_id=run.id, event_type="run.completed").count() == 0


def test_unbound_task_environment_returns_not_found(api, admin, db):
    project_id = _create_project(api, admin)
    environment_id = _make_env(db, "http://127.0.0.1:18080", _admin_id(db))
    with pytest.raises(HTTPException) as error:
        resolve_project_environment(db, project_id, environment_id)
    assert error.value.status_code == 404


def test_read_all_does_not_expose_revoked_project_notifications(api, admin, db):
    """权限撤销后，批量已读响应不能返回或修改已隐藏的任务通知。"""
    from app.core.models.identity import User
    from tests.conftest import DEFAULT_PASSWORD, unique

    project_id = _create_project(api, admin)
    username = unique("notification-member")
    assert api.register(username).status_code == 201
    api.login(username, DEFAULT_PASSWORD)
    user = db.query(User).filter_by(username=username).one()
    assert api.put(f"/projects/{project_id}/members/{user.id}", username=admin, json={"user_id": user.id, "role": "member"}).status_code == 200
    notice = Notification(user_id=user.id, project_id=project_id, event_type="task.plan_ready", title="不可再见的项目通知", is_read=False)
    db.add(notice)
    db.commit()
    notice_id = notice.id
    assert api.delete(f"/projects/{project_id}/members/{user.id}", username=admin).status_code == 204
    response = api.post("/notifications/read-all", username=username, json={"ids": [notice_id]})
    assert response.status_code == 200
    assert all(item["id"] != notice_id for item in response.json()["items"])
    db.expire_all()
    assert db.get(Notification, notice_id).is_read is False


def test_lost_web_browser_is_not_reported_active(api, admin, db):
    """浏览器句柄丢失时刷新页面明确提示，不能伪称会话恢复。"""
    from app.features.web_testing.models import WebAgentSession

    project_id = _create_project(api, admin)
    environment_id = _make_env(db, "http://127.0.0.1", _admin_id(db))
    row = WebAgentSession(project_id=project_id, environment_id=environment_id, base_url="http://127.0.0.1", status="ACTIVE", step_budget=5)
    db.add(row)
    db.commit()
    response = api.get(f"/web-agent/sessions/{row.id}", username=admin)
    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert "重新启动" in response.json()["status_reason"]


def test_task_security_finding_resource_links_are_named_and_bidirectional(api, admin, db):
    """安全任务资源能显示疑似问题名称，并从疑似问题反查正确历史运行。"""
    from app.features.security_testing.models import SecurityFinding

    project_id = _create_project(api, admin)
    user_id = _admin_id(db)
    task = Task(project_id=project_id, created_by=user_id, title="订单安全评估", goal="评估订单接口安全")
    db.add(task)
    db.flush()
    run = TaskRun(task_id=task.id, created_by=user_id, run_number=2, goal_snapshot=task.goal, input_snapshot={})
    finding = SecurityFinding(
        project_id=project_id, mutation_type="SQLI", title="订单参数疑似注入",
        description="待人工核对", fingerprint=unique("finding"), status="OPEN",
    )
    db.add_all([run, finding])
    db.flush()
    db.add(TaskResourceRef(
        task_run_id=run.id, direction="OUTPUT", resource_type="SECURITY_FINDING",
        resource_id=str(finding.id), metadata_json={"test_run_id": 42},
    ))
    db.commit()

    resources = api.get(f"/task-runs/{run.id}/resources", username=admin)
    assert resources.status_code == 200, resources.text
    assert resources.json()[0]["display_name"] == "疑似问题：订单参数疑似注入"

    reverse = api.get(
        "/task-resources", username=admin,
        params={"resource_type": "SECURITY_FINDING", "resource_id": finding.id, "project_id": project_id},
    )
    assert reverse.status_code == 200, reverse.text
    assert reverse.json()[0]["task_title"] == "订单安全评估"
    assert reverse.json()[0]["run_number"] == 2
