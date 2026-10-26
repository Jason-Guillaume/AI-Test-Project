"""统一任务 P0–P4 真实 API 集成验收。

本测试通过鉴权 HTTP API 创建任务、确认方案并观察持久化调度；测试用例、出站白名单、RunService、HTTP 执行器与 ReportService 均使用真实实现。
仅模型边界返回可重复的结构化内容，避免依赖外部 LLM 凭据；因此不作为生产模型质量验收。
"""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import inspect, text

from app.features.test_management.models.test_case import TestCase as CaseEntity
from app.models.configuration import ModelConfiguration
from tests.conftest import unique
from tests.test_15_test_executor import (
    StubServer,
    _admin_id,
    _create_case,
    _make_env,
    _make_iface,
    _whitelist,
    _create_project,
)

API = "/api/v1"


class DeterministicTaskLLM:
    """只替代外部模型 HTTP 边界，工具、业务服务和数据库链路继续真实执行。"""

    def __init__(self, db, model_config_id=None, *, model_config_ids=None, attempt_callback=None):
        """兼容生产 Provider 构造签名，不读取模型密钥。"""
        self.db = db
        self.model_config_id = model_config_id
        self.model_config_ids = model_config_ids or []
        self.attempt_callback = attempt_callback

    def generate_structured(self, system, user_content, schema=None, *, kind=None, history=None, validator=None):
        """按任务角色返回最小合法结构化文本。"""
        if kind == "task_planner":
            output = {"summary": "执行已确认的健康检查 API 用例。", "acceptance_criteria": ["产生真实 TestRun 和正式报告"]}
        elif kind in {"task_api_worker", "task_ui_worker"}:
            payload = json.loads(user_content)
            output = {"case_ids": payload["allowed_case_ids"], "explanation": "只选择已批准用例"}
        elif kind == "task_reviewer":
            output = {"approved": True, "findings": []}
        elif kind == "report_summary":
            output = {"overview": "测试执行完成。", "key_findings": [], "recommendations": [], "risk_summary": "按正式报告统计。"}
        else:
            raise AssertionError(f"未覆盖的模型角色: {kind}")
        if validator is not None:
            validator(output)
        return output

    def chat(self, system, user_content, *, history=None):
        """为主 Agent 生成与报告事实一致的简短摘要。"""
        return "主 Agent 已根据正式执行与报告记录完成汇总。"


def _seed_default_model(db, admin_id):
    """创建本测试独占的启用默认模型绑定；模型调用由测试模型边界控制。"""
    row = ModelConfiguration(
        domain_id=unique("task-model"),
        label="任务集成验证模型",
        provider="openai-compatible",
        api_base="http://127.0.0.1:9/v1",
        api_key_encrypted=None,
        model_name="test-boundary-only",
        is_enabled=True,
        is_default=True,
        created_by=admin_id,
    )
    # 平台模型表的默认位至多一个；测试隔离库内已有配置时先清除旧默认标记。
    db.query(ModelConfiguration).filter(ModelConfiguration.is_default.is_(True)).update(
        {ModelConfiguration.is_default: False}, synchronize_session=False,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_p4_migration_adds_scan_polling_and_idempotency_contract(db):
    """0016 的调度字段与 0017 的备用路由字段均已持久化。"""
    inspector = inspect(db.bind)
    assert db.execute(text("select version_num from alembic_version")).scalar() == "0017"
    assert "security_scan_json" in {item["name"] for item in inspector.get_columns("task")}
    assert "available_at" in {item["name"] for item in inspector.get_columns("task_work_item")}
    assert "idempotency_key" in {item["name"] for item in inspector.get_columns("security_scan_job")}
    assert "ix_task_work_item_available_at" in {item["name"] for item in inspector.get_indexes("task_work_item")}
    assert "uq_security_scan_job_idempotency" in {item["name"] for item in inspector.get_indexes("security_scan_job")}
    assert "fallback_model_ids" in {item["name"] for item in inspector.get_columns("model_configuration")}


def test_production_provider_falls_back_after_primary_http_error(db, monkeypatch):
    """主模型 HTTP 故障时按快照顺序调用备用模型，并校验其结构化结果。"""
    import httpx

    from app.features.agent.providers import llm_provider
    from app.features.tasks.schemas import TaskPlanOutput

    backup = ModelConfiguration(
        domain_id=unique("fallback"), label="备用模型", provider="openai-compatible",
        api_base="http://backup.invalid/v1", model_name="backup-model", is_enabled=True,
    )
    db.add(backup)
    db.flush()
    primary = ModelConfiguration(
        domain_id=unique("primary"), label="主模型", provider="openai-compatible",
        api_base="http://primary.invalid/v1", model_name="primary-model", is_enabled=True,
        fallback_model_ids=[backup.id],
    )
    db.add(primary)
    db.commit()
    calls: list[str] = []

    def post(url, *, json, headers, timeout):
        """按请求模型模拟主模型故障和备用模型成功响应。"""
        calls.append(json["model"])
        if json["model"] == "primary-model":
            return httpx.Response(503, json={"error": "unavailable"})
        return httpx.Response(200, json={
            "choices": [{"message": {"content": '{"summary":"备用接手","acceptance_criteria":["完成验证"]}'}}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 5},
        })

    monkeypatch.setattr(llm_provider.httpx, "post", post)
    events: list[dict] = []
    provider = llm_provider.ProductionLLMProvider(
        db, model_config_ids=[primary.id, backup.id], attempt_callback=events.append,
    )
    result = provider.generate_structured(
        "系统", "目标", schema=TaskPlanOutput.model_json_schema(),
        kind="task_planner", validator=TaskPlanOutput.model_validate,
    )

    assert result["summary"] == "备用接手"
    assert calls == ["primary-model", "backup-model"]
    assert provider.last_model_config_id == backup.id
    assert [event["status"] for event in events] == ["FAILED", "SUCCEEDED"]
    assert events[0]["error_code"] == "LLM_PROVIDER_ERROR"


def test_production_provider_exhaustion_is_retryable_and_redacts_response(db, monkeypatch):
    """候选模型全部超时后返回可恢复错误，不把服务端响应正文泄入事件。"""
    import httpx

    from app.features.agent.providers.llm_provider import LLMError, ProductionLLMProvider

    primary = ModelConfiguration(
        domain_id=unique("unavailable"), label="不可用模型", provider="openai-compatible",
        api_base="http://unavailable.invalid/v1", model_name="down-model", is_enabled=True,
    )
    db.add(primary)
    db.commit()
    monkeypatch.setattr(
        "app.features.agent.providers.llm_provider.httpx.post",
        lambda *args, **kwargs: httpx.Response(503, text="sensitive upstream body"),
    )
    provider = ProductionLLMProvider(db, model_config_ids=[primary.id])

    with pytest.raises(LLMError) as raised:
        provider.chat("系统", "问题")

    assert raised.value.code == "LLM_FALLBACK_EXHAUSTED"
    assert raised.value.retryable is True
    assert "sensitive upstream body" not in str(raised.value)
    assert provider.last_attempts[0]["error_code"] == "LLM_PROVIDER_ERROR"


def test_retryable_llm_failure_requeues_task_instead_of_failing(api, admin, db, monkeypatch):
    """真实任务的模型路由耗尽会持久化延迟重试，不把运行直接终止为 FAILED。"""
    from app.features.agent.providers.llm_provider import LLMError
    from app.features.tasks.runtime import worker as task_worker_module

    class UnavailableTaskLLM:
        """只模拟外部 LLM 边界连续不可用，实际调度仍由 TaskWorker 完成。"""

        def __init__(self, db, model_config_ids=None, attempt_callback=None, **kwargs):
            """保存 Worker 注入的授权候选与审计回调。"""
            self.attempt_callback = attempt_callback
            self.model_config_id = (model_config_ids or [None])[0]

        def generate_structured(self, system, user_content, schema=None, *, kind=None, history=None, validator=None):
            """模拟全部模型候选失败，并将同一错误交给 Worker 的恢复状态机。"""
            entry = {"model_config_id": self.model_config_id, "model_name": "down", "candidate_index": 0, "status": "FAILED", "error_code": "LLM_PROVIDER_ERROR"}
            if self.attempt_callback:
                self.attempt_callback(entry)
            raise LLMError("LLM_FALLBACK_EXHAUSTED", "模型路由不可用", retryable=True, attempts=[entry])

        def chat(self, system, user_content, *, history=None):
            """模拟主 Agent 会话的模型路由耗尽。"""
            raise LLMError("LLM_FALLBACK_EXHAUSTED", "模型路由不可用", retryable=True)

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", UnavailableTaskLLM)
    admin_id = _admin_id(db)
    _seed_default_model(db, admin_id)
    project_id = _create_project(api, admin)
    environment_id = _make_env(db, "http://127.0.0.1", admin_id)
    api_id = _make_iface(db, project_id, "GET", "/health", "模型降级验证接口")
    case_id = _create_case(api, admin, project_id, name=unique("fallback-case"), api_id=api_id)
    case = db.get(CaseEntity, case_id)
    case.status = "ACTIVE"
    db.commit()
    created = api.post(
        f"/projects/{project_id}/tasks", username=admin,
        json={"goal": "模型服务暂不可用时保留任务并重试", "environment_id": environment_id, "case_ids": [case_id]},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["latest_run"]["id"]

    deadline = time.monotonic() + 10
    detail = None
    while time.monotonic() < deadline:
        detail = api.get(f"/task-runs/{run_id}", username=admin).json()
        if detail["run"]["stage"] == "MODEL_RETRY":
            break
        time.sleep(0.05)

    assert detail["run"]["status"] == "QUEUED", detail
    assert detail["run"]["stage"] == "MODEL_RETRY", detail
    plan_work = next(item for item in detail["work_items"] if item["kind"] == "PLAN")
    assert plan_work["status"] == "PENDING"
    assert plan_work["error_code"] == "LLM_FALLBACK_EXHAUSTED"
    events = api.get(f"/task-runs/{run_id}/events", username=admin).json()
    assert any(event["event_type"] == "llm.retry_scheduled" for event in events)


def test_task_api_runs_existing_executor_report_and_reverse_links(api, admin, db, monkeypatch):
    """从创建、幂等、方案确认到真实 HTTP TestRun、报告和管理页回链走完闭环。"""
    from app.features.tasks.runtime import worker as task_worker_module

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", DeterministicTaskLLM)
    admin_id = _admin_id(db)
    model = _seed_default_model(db, admin_id)

    with StubServer() as stub:
        stub.add("GET", "/health", 200, {"status": "ok"})
        environment_id = _make_env(db, stub.base_url, admin_id)
        project_id = _create_project(api, admin)
        _whitelist(db, project_id, stub.port, admin_id)
        api_id = _make_iface(db, project_id, "GET", "/health", "健康检查")
        case_id = _create_case(api, admin, project_id, name=unique("health-case"), api_id=api_id)
        case = db.get(CaseEntity, case_id)
        case.status = "ACTIVE"
        db.commit()

        body = {
            "title": "真实 API 任务闭环",
            "goal": "调用已确认的健康检查用例并生成报告",
            "environment_id": environment_id,
            "case_ids": [case_id],
            "request_key": unique("request"),
        }
        created = api.post(f"/projects/{project_id}/tasks", username=admin, json=body)
        assert created.status_code == 201, created.text
        task = created.json()
        assert task["latest_run"]["status"] == "QUEUED"

        duplicate = api.post(f"/projects/{project_id}/tasks", username=admin, json=body)
        assert duplicate.status_code == 201, duplicate.text
        assert duplicate.json()["id"] == task["id"]
        mismatched_duplicate = api.post(
            f"/projects/{project_id}/tasks", username=admin,
            json={**body, "goal": "通过相同请求键提交不同目标"},
        )
        assert mismatched_duplicate.status_code == 409, mismatched_duplicate.text

        run_id = task["latest_run"]["id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            detail = api.get(f"/task-runs/{run_id}", username=admin)
            assert detail.status_code == 200, detail.text
            if detail.json()["plans"] and detail.json()["run"]["status"] == "WAITING_CONFIRMATION":
                break
            time.sleep(0.05)
        assert detail.json()["run"]["status"] == "WAITING_CONFIRMATION", detail.text
        roles = {agent["role"] for agent in detail.json()["agents"]}
        assert {"MAIN", "PLANNER", "API_WORKER", "REVIEWER", "REPORT_AGENT"} <= roles

        main_agent = next(agent for agent in detail.json()["agents"] if agent["role"] == "MAIN")
        goal_update = api.post(
            f"/task-runs/{run_id}/messages",
            username=admin,
            json={
                "recipient_instance_id": main_agent["id"],
                "message_type": "GOAL_UPDATE",
                "content": "新的整体目标仍是执行健康检查并核实正式报告",
                "client_message_id": unique("goal-update"),
            },
        )
        assert goal_update.status_code == 202, goal_update.text
        old_run = api.get(f"/task-runs/{run_id}", username=admin)
        assert old_run.json()["run"]["status"] == "SUPERSEDED"
        run_id = goal_update.json()["created_run_id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            detail = api.get(f"/task-runs/{run_id}", username=admin)
            if detail.json()["plans"] and detail.json()["run"]["status"] == "WAITING_CONFIRMATION":
                break
            time.sleep(0.05)
        assert detail.json()["run"]["status"] == "WAITING_CONFIRMATION", detail.text

        paused = api.post(
            f"/task-runs/{run_id}/commands", username=admin,
            json={"command_type": "PAUSE", "idempotency_key": unique("pause")},
        )
        assert paused.status_code == 200, paused.text
        assert paused.json()["response_json"]["status"] == "PAUSED"
        resumed = api.post(
            f"/task-runs/{run_id}/commands", username=admin,
            json={"command_type": "RESUME", "idempotency_key": unique("resume")},
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["response_json"]["status"] == "WAITING_CONFIRMATION"

        approve_key = unique("approve")
        approved = api.post(
            f"/task-runs/{run_id}/commands",
            username=admin,
            json={"command_type": "APPROVE_PLAN", "idempotency_key": approve_key},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "COMPLETED"
        duplicate_approval = api.post(
            f"/task-runs/{run_id}/commands",
            username=admin,
            json={"command_type": "APPROVE_PLAN", "idempotency_key": approve_key},
        )
        assert duplicate_approval.status_code == 200, duplicate_approval.text
        assert duplicate_approval.json()["id"] == approved.json()["id"]

        final_detail = None
        while time.monotonic() < deadline + 30:
            response = api.get(f"/task-runs/{run_id}", username=admin)
            assert response.status_code == 200, response.text
            final_detail = response.json()
            if final_detail["run"]["status"] in {"SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED", "RECONCILIATION_REQUIRED"}:
                break
            time.sleep(0.05)

        assert final_detail is not None
        assert final_detail["run"]["status"] == "SUCCEEDED", final_detail
        work_statuses = {item["kind"]: item["status"] for item in final_detail["work_items"]}
        assert work_statuses["EXECUTE_API"] == "SUCCEEDED"
        assert work_statuses["REPORT"] == "SUCCEEDED"
        assert work_statuses["REVIEW"] == "SUCCEEDED"
        assert work_statuses["FINALIZE"] == "SUCCEEDED"

        resources = api.get(f"/task-runs/{run_id}/resources", username=admin)
        assert resources.status_code == 200, resources.text
        output_types = {row["resource_type"] for row in resources.json() if row["direction"] == "OUTPUT"}
        assert {"TEST_RUN", "TEST_PLAN", "TEST_SUITE", "REPORT"} <= output_types
        test_run_ref = next(row for row in resources.json() if row["resource_type"] == "TEST_RUN")
        reverse = api.get(
            "/task-resources",
            username=admin,
            params={"resource_type": "TEST_RUN", "resource_id": test_run_ref["resource_id"]},
        )
        assert reverse.status_code == 200, reverse.text
        assert any(row["metadata_json"]["task_id"] == task["id"] for row in reverse.json())

        events = api.get(f"/task-runs/{run_id}/events", username=admin)
        assert events.status_code == 200, events.text
        event_seqs = [row["event_seq"] for row in events.json()]
        assert event_seqs == sorted(set(event_seqs))

    # 运行使用任务创建时的显式模型配置 ID；密钥没有进入实例配置快照。
    assert all(agent["model_config_id"] == model.id for agent in final_detail["agents"])
    assert all("api_key" not in json.dumps(agent["config_snapshot"]) for agent in final_detail["agents"])


def test_task_planner_retry_and_cancel_are_persisted(api, admin, db, monkeypatch):
    """Planner 的可重试失败回队列，之后可取消待确认运行且命令可幂等重放。"""
    from app.features.tasks.runtime import worker as task_worker_module

    class FailFirstPlanner(DeterministicTaskLLM):
        """首个 Planner 调用失败一次，其余模型职责复用确定性输出。"""

        planner_calls = 0

        def generate_structured(self, system, user_content, schema=None, *, kind=None, history=None, validator=None):
            """模拟一次可恢复的模型边界故障，不替代调度或业务服务。"""
            if kind == "task_planner" and type(self).planner_calls == 0:
                type(self).planner_calls += 1
                raise RuntimeError("可重试的模型边界中断")
            return super().generate_structured(system, user_content, schema, kind=kind, history=history, validator=validator)

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", FailFirstPlanner)
    admin_id = _admin_id(db)
    _seed_default_model(db, admin_id)
    project_id = _create_project(api, admin)
    environment_id = _make_env(db, "http://127.0.0.1", admin_id)
    api_id = _make_iface(db, project_id, "GET", "/health", "重试验证接口")
    case_id = _create_case(api, admin, project_id, name=unique("retry-case"), api_id=api_id)
    case = db.get(CaseEntity, case_id)
    case.status = "ACTIVE"
    db.commit()
    created = api.post(
        f"/projects/{project_id}/tasks", username=admin,
        json={"goal": "验证 Planner 安全重试", "environment_id": environment_id, "case_ids": [case_id]},
    )
    assert created.status_code == 201, created.text
    run_id = created.json()["latest_run"]["id"]

    deadline = time.monotonic() + 15
    failed_detail = None
    while time.monotonic() < deadline:
        response = api.get(f"/task-runs/{run_id}", username=admin)
        failed_detail = response.json()
        if failed_detail["run"]["status"] == "FAILED":
            break
        time.sleep(0.05)
    assert failed_detail["run"]["status"] == "FAILED", failed_detail
    plan_work = next(item for item in failed_detail["work_items"] if item["kind"] == "PLAN")

    retried = api.post(
        f"/task-runs/{run_id}/commands", username=admin,
        json={"command_type": "RETRY", "work_item_id": plan_work["id"], "idempotency_key": unique("retry")},
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["response_json"]["status"] == "QUEUED"

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        response = api.get(f"/task-runs/{run_id}", username=admin)
        detail = response.json()
        if detail["plans"]:
            break
        time.sleep(0.05)
    assert detail["run"]["status"] == "WAITING_CONFIRMATION", detail

    cancel_key = unique("cancel")
    cancelled = api.post(
        f"/task-runs/{run_id}/commands", username=admin,
        json={"command_type": "CANCEL", "idempotency_key": cancel_key},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["response_json"]["status"] == "CANCELLED"
    duplicate_cancel = api.post(
        f"/task-runs/{run_id}/commands", username=admin,
        json={"command_type": "CANCEL", "idempotency_key": cancel_key},
    )
    assert duplicate_cancel.status_code == 200, duplicate_cancel.text
    assert duplicate_cancel.json()["id"] == cancelled.json()["id"]
    conflicting_cancel = api.post(
        f"/task-runs/{run_id}/commands", username=admin,
        json={"command_type": "PAUSE", "idempotency_key": cancel_key},
    )
    assert conflicting_cancel.status_code == 409, conflicting_cancel.text


def test_task_model_binding_obeys_organization_grants(db):
    """任务创建和后台调用分别尊重组织智能体开关、模型白名单及配置停用。"""
    from app.features.tasks.services.task_service import TaskService
    from app.models.identity import Organization, OrganizationMember, User
    from app.models.project import Project
    from fastapi import HTTPException

    actor = User(username=unique("task-member"), role="test", is_active=True)
    db.add(actor)
    db.flush()
    organization = Organization(name=unique("task-org"), owner_id=actor.id)
    db.add(organization)
    db.flush()
    project = Project(name=unique("task-org-project"), owner_id=actor.id, organization_id=organization.id)
    model = ModelConfiguration(
        domain_id=unique("org-model"), label="组织授权模型", provider="openai-compatible",
        api_base="http://127.0.0.1:9/v1", model_name="test-boundary-only",
        is_enabled=True, is_default=True, created_by=actor.id,
    )
    db.add_all([project, model])
    db.flush()
    grant = OrganizationMember(
        organization_id=organization.id, user_id=actor.id, role="owner",
        agent_enabled=False, allowed_model_ids=[],
    )
    db.add(grant)
    db.commit()

    with pytest.raises(HTTPException) as disabled:
        TaskService._resolve_authorized_model(db, project.id, actor)
    assert disabled.value.status_code == 403

    grant.agent_enabled = True
    db.commit()
    with pytest.raises(HTTPException) as unassigned:
        TaskService._resolve_authorized_model(db, project.id, actor)
    assert unassigned.value.status_code == 403

    grant.allowed_model_ids = [model.domain_id]
    db.commit()
    assert TaskService._resolve_authorized_model(db, project.id, actor).id == model.id
    assert TaskService.assert_agent_model_access(db, project.id, actor, model.id).id == model.id

    grant.allowed_model_ids = []
    db.commit()
    with pytest.raises(RuntimeError, match="授权已撤销"):
        TaskService.assert_agent_model_access(db, project.id, actor, model.id)


def test_task_ui_worker_reuses_confirmed_web_testrun(api, admin, db, monkeypatch):
    """已确认 Web 用例由独立 UI Worker 走真实 TestRun/Playwright/ReportService 链。"""
    from app.features.tasks.runtime import worker as task_worker_module

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", DeterministicTaskLLM)
    admin_id = _admin_id(db)
    _seed_default_model(db, admin_id)

    with StubServer() as stub:
        stub.add("GET", "/health", 200, {"status": "ok"})
        environment_id = _make_env(db, stub.base_url, admin_id)
        project_id = _create_project(api, admin)
        _whitelist(db, project_id, stub.port, admin_id)
        created_case = api.post(
            f"/projects/{project_id}/web-cases", username=admin,
            json={"name": unique("confirmed-web-case"), "steps": [
                {"name": "打开健康页", "operation": "NAVIGATE", "value": "/health"},
            ]},
        )
        assert created_case.status_code == 201, created_case.text
        web_case_id = created_case.json()["id"]
        confirmed = api.post(
            f"/web-cases/{web_case_id}/confirm", username=admin,
            json={"revision": created_case.json()["revision"]},
        )
        assert confirmed.status_code == 200 and confirmed.json()["confirmed"]

        created = api.post(
            f"/projects/{project_id}/tasks", username=admin,
            json={"goal": "执行已确认的 Web 健康页用例并产出报告", "environment_id": environment_id, "case_ids": [web_case_id]},
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["latest_run"]["id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            detail_response = api.get(f"/task-runs/{run_id}", username=admin)
            detail = detail_response.json()
            if detail["plans"] and detail["run"]["status"] == "WAITING_CONFIRMATION":
                break
            time.sleep(0.05)
        assert {agent["role"] for agent in detail["agents"]} >= {"MAIN", "PLANNER", "UI_WORKER", "REPORT_AGENT", "REVIEWER"}
        assert "API_WORKER" not in {agent["role"] for agent in detail["agents"]}

        accepted = api.post(
            f"/task-runs/{run_id}/commands", username=admin,
            json={"command_type": "APPROVE_PLAN", "idempotency_key": unique("web-approve")},
        )
        assert accepted.status_code == 200, accepted.text
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            detail = api.get(f"/task-runs/{run_id}", username=admin).json()
            if detail["run"]["status"] in {"SUCCEEDED", "SUCCEEDED_WITH_ISSUES", "FAILED"}:
                break
            time.sleep(0.05)
        assert detail["run"]["status"] == "SUCCEEDED", detail
        assert any(item["kind"] == "EXECUTE_WEB" and item["status"] == "SUCCEEDED" for item in detail["work_items"])
        resources = api.get(f"/task-runs/{run_id}/resources", username=admin).json()
        assert any(item["resource_type"] == "TEST_RUN" for item in resources)


def test_task_security_worker_waits_for_existing_zap_job_before_report(api, admin, db, monkeypatch):
    """安全确认写入真实 ZAP job_service；报告依赖扫描终态并且不替代原 ScanWorker。"""
    from app.features.security_testing.zap.models.job import SecurityScanJob
    from app.features.tasks.models import TaskToolInvocation
    from app.features.tasks.runtime import worker as task_worker_module
    from app.shared.config import settings

    monkeypatch.setattr(task_worker_module, "ProductionLLMProvider", DeterministicTaskLLM)
    # ZAP 的原后台 Worker 在共享 TestClient 启动时保持关闭；这里验证真实 job_service 登记与调度等待，
    # 不连接 ZAP 服务或模拟扫描结果。
    monkeypatch.setattr(settings, "ZAP_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ZAP_BASE_URL", "http://1.2.3.4", raising=False)
    admin_id = _admin_id(db)
    _seed_default_model(db, admin_id)

    with StubServer() as stub:
        stub.add("GET", "/health", 200, {"status": "ok"})
        environment_id = _make_env(db, stub.base_url, admin_id)
        project_id = _create_project(api, admin)
        _whitelist(db, project_id, stub.port, admin_id)
        api_id = _make_iface(db, project_id, "GET", "/health", "含安全扫描的健康检查")
        case_id = _create_case(api, admin, project_id, name=unique("scan-case"), api_id=api_id)
        case = db.get(CaseEntity, case_id)
        case.status = "ACTIVE"
        db.commit()

        target = api.post(
            f"/projects/{project_id}/security/scan-targets", username=admin,
            json={
                "name": unique("task-scan-target"), "target_type": "API",
                "base_url": "http://1.2.3.4", "allowed_hosts": ["1.2.3.4"],
                "environment_id": environment_id, "authorization_status": "AUTHORIZED",
            },
        )
        assert target.status_code == 201, target.text
        from tests.test_29_zap_scan import _profile
        profile_id = _profile(db, project_id, scan_mode="API_PASSIVE")

        created = api.post(
            f"/projects/{project_id}/tasks", username=admin,
            json={
                "goal": "运行健康检查并等待关联的被动安全扫描完成",
                "environment_id": environment_id,
                "case_ids": [case_id],
                "security_scan": {"target_id": target.json()["id"], "scan_profile_id": profile_id},
            },
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["latest_run"]["id"]
        deadline = time.monotonic() + 15
        detail = None
        while time.monotonic() < deadline:
            detail = api.get(f"/task-runs/{run_id}", username=admin).json()
            if detail["plans"] and detail["run"]["status"] == "WAITING_CONFIRMATION":
                break
            time.sleep(0.05)
        assert detail and detail["run"]["status"] == "WAITING_CONFIRMATION", detail
        assert "SECURITY_WORKER" in {agent["role"] for agent in detail["agents"]}
        plan = detail["plans"][-1]["plan_json"]
        assert any(item["role"] == "SECURITY_WORKER" for item in plan["work_items"])

        missing_confirmation = api.post(
            f"/task-runs/{run_id}/commands", username=admin,
            json={"command_type": "APPROVE_PLAN", "idempotency_key": unique("scan-no-approval")},
        )
        assert missing_confirmation.status_code == 409, missing_confirmation.text
        approved_body = {
            "command_type": "APPROVE_PLAN", "idempotency_key": unique("scan-approval"),
            "security_scan_confirmed": True,
        }
        approved = api.post(f"/task-runs/{run_id}/commands", username=admin, json=approved_body)
        assert approved.status_code == 200, approved.text
        duplicate = api.post(f"/task-runs/{run_id}/commands", username=admin, json=approved_body)
        assert duplicate.status_code == 200 and duplicate.json()["id"] == approved.json()["id"]

        deadline = time.monotonic() + 30
        detail = None
        while time.monotonic() < deadline:
            detail = api.get(f"/task-runs/{run_id}", username=admin).json()
            scan_work = next((item for item in detail["work_items"] if item["kind"] == "SECURITY_SCAN"), None)
            if scan_work and scan_work["status"] == "PENDING" and (scan_work.get("output_json") or {}).get("scan_job_id"):
                break
            time.sleep(0.05)
        assert detail and scan_work is not None, detail
        assert scan_work["status"] == "PENDING"
        assert scan_work["output_json"]["scan_status"] == "PENDING"
        assert detail["run"]["stage"] == "SECURITY_SCAN"
        assert not any(item["kind"] == "REPORT" for item in detail["work_items"])

        scan_job = db.query(SecurityScanJob).filter(SecurityScanJob.id == scan_work["output_json"]["scan_job_id"]).one()
        assert scan_job.status == "PENDING"
        assert scan_job.test_run_id is not None
        assert scan_job.idempotency_key == f"task-run:{run_id}:security-scan:{scan_job.test_run_id}"
        assert scan_job.approved_by is None  # 被动扫描不伪造主动扫描批准人
        invocation = db.query(TaskToolInvocation).filter(
            TaskToolInvocation.task_run_id == run_id,
            TaskToolInvocation.invocation_key == f"security_scan:{scan_job.test_run_id}",
        ).one()
        assert invocation.status == "STARTED"  # 报告等待既有 ScanWorker 给出终态
        resources = api.get(f"/task-runs/{run_id}/resources", username=admin).json()
        assert any(item["resource_type"] == "SECURITY_SCAN_JOB" for item in resources)
