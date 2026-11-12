"""综合拆分中执行模式和租约代次的行为回归。"""

from datetime import datetime, timedelta

import pytest

from app.orchestration.tasks.models import Task, TaskRun, TaskWorkItem, TaskAttempt
from app.orchestration.tasks.runtime.contracts import ClaimedWork
from app.orchestration.tasks.runtime.completion_service import complete_work, fail_work
from app.core.database.session import SessionLocal
from tests.conftest import unique
from tests.test_15_test_executor import _admin_id, _create_project


@pytest.mark.parametrize("operation", ["complete", "fail"])
@pytest.mark.parametrize("new_owner", ["old-owner", "new-owner"])
def test_late_attempt_cannot_overwrite_current_generation(api, admin, db, operation, new_owner):
    """即使同一 Worker 重新领取，旧代次完成/失败也不能清除新租约或覆盖状态。"""
    project_id = _create_project(api, admin)
    actor_id = _admin_id(db)
    task = Task(project_id=project_id, created_by=actor_id, title=unique("late-attempt"), goal="租约代次验证", status="RUNNING")
    db.add(task)
    db.flush()
    run = TaskRun(task_id=task.id, run_number=1, created_by=actor_id, goal_snapshot=task.goal,
                  status="RUNNING", lease_owner=new_owner, lease_expires_at=datetime.now() + timedelta(hours=1))
    db.add(run)
    db.flush()
    work = TaskWorkItem(task_run_id=run.id, work_key="late-result", kind="PLAN", status="RUNNING",
                        attempt_count=2, idempotency_key=unique("late-key"))
    db.add(work)
    db.flush()
    old_attempt = TaskAttempt(work_item_id=work.id, attempt_number=1, lease_generation=1,
                              owner="old-owner", status="RUNNING")
    db.add(old_attempt)
    db.flush()
    db.add(TaskAttempt(work_item_id=work.id, attempt_number=2, lease_generation=2,
                       owner=new_owner, status="RUNNING"))
    db.commit()
    claim = ClaimedWork(work.id, run.id, old_attempt.id, "old-owner")
    if operation == "complete":
        complete_work(db, task, run, work, old_attempt, None)
    else:
        fail_work(claim, RuntimeError("迟到异常"), db_factory=SessionLocal)
    db.expire_all()
    assert run.status == "RUNNING"
    assert run.lease_owner == new_owner
    assert work.status == "RUNNING"
    assert work.attempt_count == 2
    assert old_attempt.status == "RUNNING"
    assert work.error_code is None
    assert run.event_seq == 0
    # 让后台 Worker 不再考虑本条测试记录；不清理任何真实任务。
    run.lease_owner = None
    run.lease_expires_at = None
    run.status = task.status = "CANCELLED"
    work.status = "CANCELLED"
    db.commit()


@pytest.mark.parametrize("binding_kind", ["missing", "cross_project"])
def test_invalid_action_target_does_not_generate_faker(api, admin, db, monkeypatch, binding_kind):
    """默认绑定/项目校验先于 Faker 求值；重构不能提前产生用例数据。"""
    from app.core.models.configuration import Environment
    from app.core.models.identity import User
    from app.features.business.models.business_domain import BusinessDomain
    from app.features.business.models.business_flow import BusinessFlow
    from app.features.business.models.business_binding import BusinessBinding
    from app.features.test_management.models.test_case import TestCase as Case
    from app.features.test_management.models.test_case_data import TestCaseData as CaseData
    from app.features.test_management.executors import preparation, test_case_executor
    from tests.test_15_test_executor import _add_action, _make_env, _make_iface

    project = _create_project(api, admin)
    actor_id = _admin_id(db)
    env_id = _make_env(db, "http://127.0.0.1:9", actor_id)
    domain = BusinessDomain(project_id=project, name=unique("action-order"))
    db.add(domain)
    db.flush()
    flow = BusinessFlow(project_id=project, domain_id=domain.id, name=unique("flow-order"), status="ACTIVE")
    db.add(flow)
    db.flush()
    action = _add_action(db, flow.id, "动作目标准备", "TARGET_ORDER", 1)
    if binding_kind == "cross_project":
        other_project = _create_project(api, admin)
        iface = _make_iface(db, other_project, "POST", "/never", "不可执行目标")
        db.add(BusinessBinding(action_id=action.id, binding_type="API", api_id=iface, is_default=True, enabled=True))
    case = Case(project_id=project, name=unique("data-order"), target_type="BUSINESS_ACTION", business_action_id=action.id)
    db.add(case)
    db.flush()
    db.add(CaseData(test_case_id=case.id, name="generated", source_type="FAKER", value_type="STRING",
                    config_json={"generator": "uuid"}))
    db.commit()
    calls = []
    monkeypatch.setattr(preparation, "generate_faker_value", lambda *args, **kwargs: calls.append(1) or "generated")
    result = test_case_executor.execute(db, case, environment=db.get(Environment, env_id), actor=db.get(User, actor_id))
    assert result.status == "ERROR"
    assert result.error_code == ("DEFAULT_BINDING_NOT_FOUND" if binding_kind == "missing" else "API_NOT_FOUND")
    assert calls == []


def test_case_action_keeps_data_separate_from_runtime_headers(api, admin, db, monkeypatch):
    """保留名称的数据映射值不能被 Mock 平台头覆盖，也不能自动成为 HTTP 头。"""
    import json
    from app.core.models.configuration import Environment
    from app.core.models.identity import User
    from app.features.business.models.business_domain import BusinessDomain
    from app.features.business.models.business_flow import BusinessFlow
    from app.features.business.models.business_binding import BusinessBinding
    from app.features.business.models.business_api_mapping import BusinessApiMapping
    from app.features.business.executors import action_executor
    from app.features.test_management.models.test_case import TestCase as Case
    from app.features.test_management.models.test_case_data import TestCaseData as CaseData
    from app.features.test_management.executors import test_case_executor
    from app.execution.http.contracts import HttpExecutionResult
    from tests.test_15_test_executor import _add_action, _make_env, _make_iface

    project = _create_project(api, admin)
    actor_id = _admin_id(db)
    env_id = _make_env(db, "http://127.0.0.1:9", actor_id)
    iface_id = _make_iface(db, project, "POST", "/header-contract", "请求头边界")
    domain = BusinessDomain(project_id=project, name=unique("header-data"))
    db.add(domain)
    db.flush()
    flow = BusinessFlow(project_id=project, domain_id=domain.id, name=unique("header-flow"), status="ACTIVE")
    db.add(flow)
    db.flush()
    action = _add_action(db, flow.id, "普通数据与平台头", "HEADER_DATA", 1)
    binding = BusinessBinding(action_id=action.id, binding_type="API", api_id=iface_id, is_default=True, enabled=True)
    db.add(binding)
    db.flush()
    db.add(BusinessApiMapping(binding_id=binding.id, direction="INPUT", business_variable="__web_headers",
                              api_location="BODY", api_field="payload"))
    case = Case(project_id=project, name=unique("header-case"), target_type="BUSINESS_ACTION", business_action_id=action.id)
    db.add(case)
    db.flush()
    data = {"Unexpected": "ordinary-data"}
    db.add(CaseData(test_case_id=case.id, name="__web_headers", source_type="STATIC", value_type="OBJECT", value=json.dumps(data)))
    db.commit()
    calls = []

    def capture_send(db, **kwargs):
        """只替代 HTTP 边界，真实默认绑定、输入映射和测试适配继续执行。"""
        calls.append(kwargs)
        response = HttpExecutionResult()
        response.status_code = 200
        response.response_body = '{"ok":true}'
        return response

    monkeypatch.setattr(action_executor._EXECUTOR, "execute", capture_send)
    result = test_case_executor.execute(db, case, environment=db.get(Environment, env_id), actor=db.get(User, actor_id),
                                        extra_headers={"X-Mock-Context": "controlled-context"})
    assert result.status == "PASSED"
    assert len(calls) == 1
    assert calls[0]["json_body"] == {"payload": data}
    assert calls[0]["headers"]["X-Mock-Context"] == "controlled-context"
    assert "Unexpected" not in calls[0]["headers"]
