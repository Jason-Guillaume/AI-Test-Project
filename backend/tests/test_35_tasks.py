"""统一任务 P0–P3 真实 API 集成验收。

本测试通过鉴权 HTTP API 创建任务、确认方案并观察持久化调度；测试用例、出站白名单、RunService、HTTP 执行器与 ReportService 均使用真实实现。
仅模型边界返回可重复的结构化内容，避免依赖外部 LLM 凭据；因此不作为生产模型质量验收。
"""

from __future__ import annotations

import json
import time

import pytest

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

    def __init__(self, db, model_config_id=None):
        """兼容生产 Provider 构造签名，不读取模型密钥。"""
        self.db = db
        self.model_config_id = model_config_id

    def generate_structured(self, system, user_content, schema=None, *, kind=None, history=None):
        """按任务角色返回最小合法结构化文本。"""
        if kind == "task_planner":
            return {"summary": "执行已确认的健康检查 API 用例。", "acceptance_criteria": ["产生真实 TestRun 和正式报告"]}
        if kind == "task_api_worker":
            payload = json.loads(user_content)
            return {"case_ids": payload["allowed_case_ids"], "explanation": "只选择已批准用例"}
        if kind == "task_reviewer":
            return {"approved": True, "findings": []}
        if kind == "report_summary":
            return {"overview": "测试执行完成。", "key_findings": [], "recommendations": [], "risk_summary": "按正式报告统计。"}
        raise AssertionError(f"未覆盖的模型角色: {kind}")

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

        def generate_structured(self, system, user_content, schema=None, *, kind=None, history=None):
            """模拟一次可恢复的模型边界故障，不替代调度或业务服务。"""
            if kind == "task_planner" and type(self).planner_calls == 0:
                type(self).planner_calls += 1
                raise RuntimeError("可重试的模型边界中断")
            return super().generate_structured(system, user_content, schema, kind=kind, history=history)

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
